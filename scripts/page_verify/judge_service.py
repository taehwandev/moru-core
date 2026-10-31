#!/usr/bin/env python3
"""A small HTTP service that derives checklists and judges evidence, holding the model key.

The agent session that builds a page must not be able to read the provider key, so
the session sends its request and its observation evidence here and gets items and
verdicts back. The key stays in this process.

POST /derive  {"request": str}                       -> {"items": [...]}
POST /state   {"op": "get"|"put", "key": str, "value": dict|null}  -> {"value": ...}
POST /judge   {"items": [...], "evidence": {...}, "source": "<line-numbered code>",
               "images": {"<file>": "<base64 jpeg>"}} -> {"results": [...]}

Requests need ``Authorization: Bearer <token>``; the token is read from a file or the environment, never an argument (it would show in process lists). The token only limits who may spend
the key; it is not the key.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import verify  # noqa: E402

MAX_BODY_BYTES = 40 * 1024 * 1024
MAX_STATE_KEYS = 256
STATE: dict[str, dict] = {}  # hook state kept here so the checked session cannot rewrite its own rounds


def make_handler(token: str, *, derive=None, judge=None):
    derive = derive or verify.derive_checklist
    judge = judge or verify.judge_loaded

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # noqa: D102 - keep the key holder's console quiet
            return

        def reply(self, status: int, body: dict) -> None:
            data = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):  # noqa: N802 - http.server API
            if self.headers.get("Authorization") != f"Bearer {token}":
                return self.reply(401, {"error": "unauthorized"})
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_BODY_BYTES:
                return self.reply(413, {"error": "body size not accepted"})
            try:
                body = json.loads(self.rfile.read(length))
                if self.path == "/derive":
                    return self.reply(200, {"items": derive(str(body["request"]))})
                if self.path == "/judge":
                    results = judge(body["items"], body["evidence"], body["images"])
                    results = verify.combine(results, verify.judge_code(body["items"], str(body.get("source") or "")))
                    return self.reply(200, {"results": results})
                if self.path == "/state":
                    key = str(body["key"])[:200]
                    if body.get("op") == "put":
                        value = body.get("value")
                        if value is None:
                            STATE.pop(key, None)
                        elif isinstance(value, dict) and (key in STATE or len(STATE) < MAX_STATE_KEYS):
                            STATE[key] = value
                        return self.reply(200, {"ok": True})
                    return self.reply(200, {"value": STATE.get(key)})
                return self.reply(404, {"error": "unknown path"})
            except Exception as error:  # noqa: BLE001 - report, never crash the service
                return self.reply(500, {"error": f"{type(error).__name__}: {str(error)[:200]}"})

    return Handler


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--token-file", help="file holding the bearer token (default: MORU_VERIFY_JUDGE_TOKEN); never pass the token as an argument")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--bind", default="127.0.0.1")
    args = parser.parse_args(argv)
    token = (Path(args.token_file).read_text().strip() if args.token_file else os.environ.get("MORU_VERIFY_JUDGE_TOKEN", ""))
    if not token:
        parser.error("set --token-file or MORU_VERIFY_JUDGE_TOKEN")
    verify.api_key()  # fail now, not on the first request
    server = ThreadingHTTPServer((args.bind, args.port), make_handler(token))
    print(f"judge service on {args.bind}:{args.port}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
