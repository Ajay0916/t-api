"""Vj-wz style logging setup — FileHandler(log.txt) + StreamHandler."""
import logging
import os
import sys

LOG_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "log.txt")
_FORMAT = "[%(asctime)s] [%(levelname)s] - %(message)s"
_DATEFMT = "%d-%b-%y %I:%M:%S %p"


def setup_logging(level=logging.INFO):
    """Configure root logger with FileHandler + StreamHandler (Vj-wz style)."""
    root = logging.getLogger()
    if root.handlers:
        return  # already configured

    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATEFMT))

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATEFMT))

    root.setLevel(level)
    root.addHandler(file_handler)
    root.addHandler(stream_handler)

    # Suppress noisy libraries
    for name in ("aiohttp", "urllib3", "curl_cffi", "uvicorn.access"):
        logging.getLogger(name).setLevel(logging.WARNING)

    logging.getLogger("uvicorn").setLevel(logging.INFO)


def get_logger(name="tapi"):
    """Get a named logger."""
    return logging.getLogger(name)
