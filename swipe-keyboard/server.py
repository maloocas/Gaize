"""Serves the demo and forwards POST /llm to the OpenAI Responses API, so the key stays server-side.

    OPENAI_API_KEY=sk-... python3 server.py
"""
import http.server
import json
import os
import urllib.error
import urllib.request

KEY = os.environ["OPENAI_API_KEY"]
assert KEY, "OPENAI_API_KEY is empty"
# Spend guards: the server, not the page, fixes the model and output cap, and stops after MAX_CALLS.
MODEL = "gpt-5.6-luna"
MAX_OUTPUT_TOKENS = 200
MAX_INPUT_BYTES = 8000
MAX_CALLS = int(os.environ.get("MAX_CALLS", 300))
calls = 0


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_POST(self):
        global calls
        if self.path != "/llm":
            return self.send_error(404)
        size = int(self.headers["Content-Length"])
        if size > MAX_INPUT_BYTES or calls >= MAX_CALLS:
            return self.send_error(429, "request too large or call limit reached; restart server.py")
        calls += 1
        req_json = json.loads(self.rfile.read(size))
        req_json.update(model=MODEL, max_output_tokens=MAX_OUTPUT_TOKENS, stream=False)
        body = json.dumps(req_json).encode()
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
