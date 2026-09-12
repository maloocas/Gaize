"""Serves the demo and forwards POST /llm to the OpenAI Responses API, so the key stays server-side.

    OPENAI_API_KEY=sk-... python3 server.py
"""
import http.server
import os
import urllib.error
import urllib.request

KEY = os.environ["OPENAI_API_KEY"]


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/llm":
            return self.send_error(404)
        body = self.rfile.read(int(self.headers["Content-Length"]))
        req = urllib.request.Request(
            "https://api.openai.com/v1/responses",
            data=body,
            headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req) as r:
                status, data = r.status, r.read()
        except urllib.error.HTTPError as e:
            status, data = e.code, e.read()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)


os.chdir(os.path.dirname(os.path.abspath(__file__)))
http.server.ThreadingHTTPServer(("", 8000), Handler).serve_forever()
