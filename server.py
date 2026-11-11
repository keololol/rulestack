"""
Rulestack local server: serves this folder AND keeps your Finnhub key private.

Why this exists
---------------
Anything inside an HTML file can be read by whoever opens it (press F12).
So the key lives here, on the server side, and the page asks this server for
prices. The browser never sees the key.

    browser  --->  http://127.0.0.1:8000/api/quote?symbol=AAPL  --->  this server
                                                                      (adds the key)
                                                                         |
                                                                         v
                                                                  finnhub.io

How to run
----------
1. Put your key in a file called  .env  next to this script:
       FINNHUB_KEY=your_key_here
   (copy .env.example to .env and edit it)
2. Run:   py server.py
3. Open:  http://127.0.0.1:8000/v2.html

Only uses Python's standard library: nothing to install.
"""
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Default: only reachable from this computer.
# To open the site on your phone (same Wi-Fi), start with HOST=0.0.0.0:
#     PowerShell:  $env:HOST="0.0.0.0"; py server.py
# then visit  http://<this computer's IP address>:8000/v2.html  on the phone.
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8000"))
SYMBOL = re.compile(r"^[A-Z0-9.\-]{1,12}$")
CACHE_SECONDS = 60                      # reuse a quote for a minute to save your free-plan calls
BLOCKED = {"server.py", ".env", ".env.example", ".gitignore"}


def load_key():
    """Read FINNHUB_KEY from the environment, or from a .env file next to this script."""
    key = os.environ.get("FINNHUB_KEY", "").strip()
    env_file = HERE / ".env"
    if not key and env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("FINNHUB_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
    return key


KEY = load_key()
cache = {}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(HERE), **kwargs)

    def send_json(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        if url.path == "/api/health":
            return self.send_json(200, {"ok": True, "key": bool(KEY)})
        if url.path == "/api/quote":
            symbol = urllib.parse.parse_qs(url.query).get("symbol", [""])[0]
            return self.quote(symbol)
        # Never hand out the key file, this script, or any hidden file.
        name = Path(urllib.parse.unquote(url.path)).name
        if name in BLOCKED or name.startswith("."):
            return self.send_error(404)
        return super().do_GET()

    def list_directory(self, path):
        # No folder listings: they would reveal file names.
        self.send_error(404)
        return None

    def quote(self, symbol):
        symbol = symbol.upper()
        if not KEY:
            return self.send_json(503, {"error": "No FINNHUB_KEY on the server. Add it to .env and restart."})
        if not SYMBOL.match(symbol):
            return self.send_json(400, {"error": "Bad symbol."})
        hit = cache.get(symbol)
        if hit and time.time() - hit[0] < CACHE_SECONDS:
            return self.send_json(200, hit[1])
        query = urllib.parse.urlencode({"symbol": symbol, "token": KEY})
        try:
            with urllib.request.urlopen("https://finnhub.io/api/v1/quote?" + query, timeout=10) as r:
                data = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return self.send_json(e.code, {"error": "Finnhub replied " + str(e.code) + "."})
        except Exception:
            return self.send_json(502, {"error": "Couldn't reach Finnhub."})
        cache[symbol] = (time.time(), data)
        return self.send_json(200, data)


if __name__ == "__main__":
    print("Rulestack server")
    print("  Finnhub key:", "found" if KEY else "MISSING (add FINNHUB_KEY to .env)")
    print("  Open:        http://%s:%d/v2.html" % (HOST, PORT))
    print("  Stop:        Ctrl+C")
    try:
        ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
