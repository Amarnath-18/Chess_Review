"""A stand-in for an OpenAI-compatible model, for browser tests only.

It reads the engine facts it is given and answers with a grounded explanation (so the app's real
validation passes). Special requests let a test exercise the failure paths:
  - asked to explain for an "advanced" player it invents a move (the app must fall back);
It never leaves the compose network and needs no key.
"""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("content-length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        user = next((m["content"] for m in body.get("messages", []) if m["role"] == "user" and m["content"].startswith("Engine facts:")), "")
        facts = json.loads(user.split("\n", 1)[1]) if user else {}
        played = facts.get("played", {}).get("san", "your move")
        best = facts.get("engine_best", {}).get("san", "the best move")
        system = next((m["content"] for m in body.get("messages", []) if m["role"] == "system"), "")
        if "advanced player" in system:
            text = "You should consider Qh5 here."  # not an allowed move: must be rejected
            moves = ["Qh5"]
        else:
            text = f"You played {played}, but the engine preferred {best}."
            moves = [played] if played == best else [played, best]
        reply = {"explanation": text, "mentioned_moves": moves, "motif": None}
        out = json.dumps({"choices": [{"message": {"content": json.dumps(reply)}}], "usage": {"prompt_tokens": 300, "completion_tokens": 40}}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *_):
        pass


HTTPServer(("0.0.0.0", 8099), Handler).serve_forever()
