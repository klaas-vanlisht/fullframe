"""Tiny local web server: serves the UI and a JSON API."""
import json
import mimetypes
import os
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import export, views
from .db import DB
from .pipeline import Pipeline
from .util import DATA_DIR, ROOT, load_config, load_sources

WEB = os.path.join(ROOT, "web")
EXPORT = os.path.join(DATA_DIR, "export")


class App:
    def __init__(self):
        self.cfg = load_config()
        self.sources = load_sources()
        self.db = DB()
        self.pipeline = Pipeline(self.cfg, self.db, self.sources)
        self.pipeline.after_run = self.export

    def export(self):
        export.export(self.db, self.sources, self.cfg, EXPORT, public=False, ai_status=self.pipeline.status["ai"])


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Fullframe/1.0"

        def log_message(self, fmt, *args):  # keep the console quiet
            pass

        def _send(self, code, body, ctype="application/json; charset=utf-8", cache=False):
            if isinstance(body, (dict, list)):
                body = json.dumps(body, ensure_ascii=False).encode("utf-8")
            elif isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "max-age=300" if cache else "no-cache")
            self.end_headers()
            self.wfile.write(body)

        def _static(self, path):
            rel = "index.html" if path in ("", "/") else path.lstrip("/")
            if rel.startswith("data/"):
                full = os.path.normpath(os.path.join(EXPORT, rel))
                if not full.startswith(EXPORT + os.sep) or not os.path.isfile(full):
                    return self._send(404, {"error": "not found"})
            else:
                full = os.path.normpath(os.path.join(WEB, rel))
                if not full.startswith(WEB + os.sep) or not os.path.isfile(full):
                    full = os.path.join(WEB, "index.html")
            ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype.endswith("javascript"):
                ctype += "; charset=utf-8"
            with open(full, "rb") as f:
                self._send(200, f.read(), ctype)

        def do_GET(self):
            u = urllib.parse.urlsplit(self.path)
            qs = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
            p = u.path
            try:
                if p == "/api/status":
                    return self._send(200, {**app.pipeline.status, "stats": views.stats(app.db),
                                            "refresh_minutes": app.cfg["refresh_minutes"]})
                if p.startswith("/api/"):
                    return self._send(404, {"error": "unknown endpoint"})
                return self._static(p)
            except Exception as e:  # noqa: BLE001
                return self._send(500, {"error": str(e)})

        def do_POST(self):
            p = urllib.parse.urlsplit(self.path).path
            if p == "/api/refresh":
                app.pipeline.trigger()
                return self._send(202, {"ok": True})
            if p.startswith("/api/story/") and p.endswith("/resummarize"):
                sid = int(p.split("/")[3])
                app.pipeline.trigger(resummarize_story=sid)
                return self._send(202, {"ok": True})
            return self._send(404, {"error": "unknown endpoint"})

    return Handler


def main():
    app = App()
    host, port = app.cfg["host"], int(app.cfg["port"])
    httpd = ThreadingHTTPServer((host, port), make_handler(app))
    url = "http://%s:%d/" % ("localhost" if host in ("127.0.0.1", "0.0.0.0") else host, port)
    llm_ = app.pipeline.llm
    ai_line = ("AI summaries: ON via %s (model: %s)" % (llm_.name, llm_.model) if llm_ else
               "AI summaries: OFF - no Gemini key or Claude Code found (see README). Stories still work without summaries.")
    print("\n  Fullframe is running at %s\n  %s\n  %d outlets loaded. Press Ctrl+C to stop.\n" % (url, ai_line, len(app.sources)),
          flush=True)
    app.export()  # show what's already in the database right away
    app.pipeline.start()
    if app.cfg.get("open_browser", True):
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nBye.")


if __name__ == "__main__":
    main()
