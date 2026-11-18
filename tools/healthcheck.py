import os
import urllib.request

host = (os.environ.get("STRONG_ALLOWED_HOSTS") or "localhost").split(",")[0].strip()
if not host or host == "*":
    host = "localhost"
host = host.lstrip(".")
port = os.environ.get("STRONG_PORT") or "8000"

request = urllib.request.Request(
    f"http://127.0.0.1:{port}/api/v1/healthz",
    headers={"Host": host},
)
urllib.request.urlopen(request, timeout=5)
