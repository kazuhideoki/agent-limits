"""Serve the dashboard to a browser on this Mac."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import errno
import json
import sys
from threading import Lock

from limits_dashboard import assemble_dashboard, collect_dashboard, collect_part, dashboard_keys, render_dashboard


DEFAULT_PORT = 43871


def serve(service, read_claude, read_agy):
  address = ("127.0.0.1", DEFAULT_PORT)

  keys = dashboard_keys(service)
  latest = {}
  refresh_lock = Lock()

  class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
      if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}":
        self.send_error(403)
        return
      if self.path == "/":
        data = assemble_dashboard(keys, latest.copy())
        body = render_dashboard(data, live=True)
        mime = "text/html"
      elif self.path == "/health" and service is None:
        body = "agent-limits-dashboard-v1"
        mime = "text/plain"
      elif self.path in ("/api/limits", "/api/refresh"):
        if self.headers.get("X-Agent-Limits") != "dashboard":
          self.send_error(403)
          return
        if self.path == "/api/refresh":
          self.stream_refresh()
          return
        with refresh_lock:
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

    def stream_refresh(self):
      self.send_response(200)
      self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
      self.send_header("Cache-Control", "no-store")
      self.end_headers()
      connected = True
      with refresh_lock, ThreadPoolExecutor(max_workers=len(keys)) as pool:
        pending = {pool.submit(collect_part, key, read_claude, read_agy): key for key in keys}
        for task in as_completed(pending):
          key = pending[task]
          part, _ = task.result()
          latest[key] = part
          if connected:
            try:
              line = json.dumps({"key": key, **part}, ensure_ascii=False) + "\n"
              self.wfile.write(line.encode("utf-8"))
              self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
              connected = False

  try:
    try:
      server = ThreadingHTTPServer(address, Handler)
    except OSError as error:
      if error.errno != errno.EADDRINUSE:
        raise
      server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    with server:
      print(f"http://127.0.0.1:{server.server_port}/", flush=True)
      server.serve_forever()
  except KeyboardInterrupt:
    pass
  except OSError as error:
    print(error, file=sys.stderr)
    return 1
  return 0
