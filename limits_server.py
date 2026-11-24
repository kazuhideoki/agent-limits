"""Serve the dashboard to a browser on this Mac."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import sys

from limits_dashboard import collect_dashboard, render_dashboard


def serve(service, read_claude, read_agy):
  address = ("127.0.0.1", 8765)
  host = f"{address[0]}:{address[1]}"

  class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
      if self.headers.get("Host") != host:
        self.send_error(403)
        return
      if self.path == "/":
        data = dict(snapshot="最新の利用枠を取得中…", rows="", other="", tickets="")
        body = render_dashboard(data, live=True)
        mime = "text/html"
      elif self.path == "/api/limits":
        if self.headers.get("X-Agent-Limits") != "dashboard":
          self.send_error(403)
          return
        data, _ = collect_dashboard(service, read_claude, read_agy)
        body = json.dumps(data, ensure_ascii=False)
        mime = "application/json"
      else:
        self.send_error(404)
        return
      payload = body.encode("utf-8")
      self.send_response(200)
      self.send_header("Content-Type", mime + "; charset=utf-8")
      self.send_header("Content-Length", str(len(payload)))
      self.send_header("Cache-Control", "no-store")
      self.send_header("X-Frame-Options", "DENY")
      self.end_headers()
      try:
        self.wfile.write(payload)
      except (BrokenPipeError, ConnectionResetError):
        pass

  try:
    with ThreadingHTTPServer(address, Handler) as server:
      print(f"http://{host}/", flush=True)
      server.serve_forever()
  except KeyboardInterrupt:
    pass
  except OSError as error:
    print(error, file=sys.stderr)
    return 1
  return 0
