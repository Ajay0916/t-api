"""Minimal SOCKS5 proxy that binds outgoing connections to wg1 VPN IP.

Listens on 127.0.0.1:1080. All outgoing TCP connections are made from
10.2.0.2 (wg1 interface IP), so routing rules send traffic through VPN.

Usage:  python3 wg1_proxy.py          (foreground)
        systemctl start wg1-proxy     (via systemd)
"""
import asyncio
import struct
import logging
import signal

LOG = logging.getLogger("wg1-proxy")
WG1_SRC = "10.2.0.2"
LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 1080
BUFSIZE = 65536


async def pipe(reader, writer):
    try:
        while True:
            data = await reader.read(BUFSIZE)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except (ConnectionError, OSError, asyncio.CancelledError):
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def handle(client_reader, client_writer):
    try:
        header = await asyncio.wait_for(client_reader.readexactly(2), timeout=10)
        nmethods = header[1]
        await asyncio.wait_for(client_reader.readexactly(nmethods), timeout=5)
        client_writer.write(b"\x05\x00")
        await client_writer.drain()

        req = await asyncio.wait_for(client_reader.readexactly(4), timeout=10)
        ver, cmd, _rsv, atyp = req[0], req[1], req[2], req[3]
        if ver != 0x05 or cmd != 0x01:
            client_writer.write(b"\x05\x07\x00\x01\x00\x00\x00\x00\x00\x00")
            await client_writer.drain()
            return

        if atyp == 1:
            raw = await asyncio.wait_for(client_reader.readexactly(4), timeout=5)
            addr = ".".join(str(b) for b in raw)
            port_data = await asyncio.wait_for(client_reader.readexactly(2), timeout=5)
        elif atyp == 3:
            dlen = (await asyncio.wait_for(client_reader.readexactly(1), timeout=5))[0]
            domain = (await asyncio.wait_for(client_reader.readexactly(dlen), timeout=5)).decode()
            addr = domain
            port_data = await asyncio.wait_for(client_reader.readexactly(2), timeout=5)
        elif atyp == 4:
            raw = await asyncio.wait_for(client_reader.readexactly(16), timeout=5)
            addr = ":".join(f"{raw[i]:02x}{raw[i+1]:02x}" for i in range(0, 16, 2))
            port_data = await asyncio.wait_for(client_reader.readexactly(2), timeout=5)
        else:
            client_writer.write(b"\x05\x08\x00\x01\x00\x00\x00\x00\x00\x00")
            await client_writer.drain()
            return

        port = struct.unpack("!H", port_data)[0]

        try:
            remote_reader, remote_writer = await asyncio.wait_for(
                asyncio.open_connection(addr, port, local_addr=(WG1_SRC, 0)),
                timeout=15,
            )
        except Exception as e:
            LOG.debug("connect failed %s:%d: %s", addr, port, e)
            client_writer.write(b"\x05\x05\x00\x01\x00\x00\x00\x00\x00\x00")
            await client_writer.drain()
            return

        client_writer.write(b"\x05\x00\x00\x01\x7f\x00\x00\x01\x00\x00")
        await client_writer.drain()

        await asyncio.gather(
            pipe(client_reader, remote_writer),
            pipe(remote_reader, client_writer),
            return_exceptions=True,
        )
    except (asyncio.TimeoutError, asyncio.IncompleteReadError):
        pass
    except Exception as e:
        LOG.debug("handler error: %s", e)
    finally:
        try:
            client_writer.close()
        except Exception:
            pass


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    server = await asyncio.start_server(handle, LISTEN_HOST, LISTEN_PORT)
    LOG.info("SOCKS5 proxy on %s:%d (outbound via %s)", LISTEN_HOST, LISTEN_PORT, WG1_SRC)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    server.close()
    await server.wait_closed()


if __name__ == "__main__":
    asyncio.run(main())
