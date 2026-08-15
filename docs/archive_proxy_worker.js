// Cloudflare Worker - archive.org proxy for t-api (bypasses datacenter IP
// throttling: requests egress from Cloudflare IPs instead of the VPS).
// Deploy: workers.cloudflare.com -> Create Worker -> paste -> Deploy.
// Then set t-api env: INTERNETARCHIVE_URL=https://<name>.<subdomain>.workers.dev
export default {
  async fetch(request) {
    const url = new URL(request.url);
    if (url.pathname === "/" || url.pathname === "/health") {
      return new Response("ok", { headers: { "Access-Control-Allow-Origin": "*" } });
    }
    const target = new URL("https://archive.org");
    target.pathname = url.pathname;
    target.search = url.search;
    const upstream = await fetch(target.toString(), {
      headers: {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) t-api-archive-proxy",
        "Accept": request.headers.get("Accept") || "*/*",
      },
      redirect: "follow",
    });
    const headers = new Headers(upstream.headers);
    headers.set("Access-Control-Allow-Origin", "*");
    headers.set("Cache-Control", "public, max-age=60");
    return new Response(upstream.body, { status: upstream.status, headers });
  },
};
