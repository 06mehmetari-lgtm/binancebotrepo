"""
LLM Relay — Groq/Cerebras OpenAI proxy.

Cloudflare 1010 alan VPS'ten değil; ev PC / farklı sunucuda çalıştırın.
VPS .env: LLM_RELAY_URL=http://<relay-host>:8099

  docker compose --profile relay up -d llm_relay   # relay makinesinde
  cloudflared tunnel --url http://127.0.0.1:8099  # veya Cloudflare Tunnel
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

UPSTREAM = {
    "groq": os.getenv("RELAY_GROQ_UPSTREAM", "https://api.groq.com/openai/v1").rstrip("/"),
    "cerebras": os.getenv("RELAY_CEREBRAS_UPSTREAM", "https://api.cerebras.ai/v1").rstrip("/"),
}
SECRET = (os.getenv("LLM_RELAY_SECRET") or "").strip()
PORT = int(os.getenv("LLM_RELAY_PORT", "8099"))
TIMEOUT = float(os.getenv("LLM_RELAY_TIMEOUT", "120"))


def _auth_ok(handler: BaseHTTPRequestHandler) -> bool:
    if not SECRET:
        return True
    auth = handler.headers.get("Authorization", "")
    if auth == f"Bearer {SECRET}":
        return True
    if handler.headers.get("X-Relay-Secret", "") == SECRET:
        return True
    return False


class RelayHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:
        log.info("%s - %s", self.address_string(), fmt % args)

    def _send_json(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path.rstrip("/") in ("", "/health"):
            self._send_json(
                200,
                {
                    "ok": True,
                    "service": "llm_relay",
                    "providers": list(UPSTREAM.keys()),
                },
            )
            return
        self._send_json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        if not _auth_ok(self):
            self._send_json(401, {"error": "unauthorized", "hint": "Set LLM_RELAY_SECRET + X-Relay-Secret"})
            return

        parts = self.path.strip("/").split("/")
        # /groq/v1/chat/completions
        if len(parts) < 4 or parts[0] not in UPSTREAM or parts[-2:] != ["chat", "completions"]:
            self._send_json(
                404,
                {
                    "error": "bad_path",
                    "expected": "/groq/v1/chat/completions or /cerebras/v1/chat/completions",
                },
            )
            return

        provider = parts[0]
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length) if length else b""
        upstream = f"{UPSTREAM[provider]}/chat/completions"
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            self._send_json(400, {"error": "missing Authorization: Bearer <provider_api_key>"})
            return

        req = urllib.request.Request(
            upstream,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": auth,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                data = resp.read()
                self.send_response(resp.status)
                ct = resp.headers.get("Content-Type", "application/json")
                self.send_header("Content-Type", ct)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        except urllib.error.HTTPError as e:
            err = e.read()
            self.send_response(e.code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(err)))
            self.end_headers()
            self.wfile.write(err)
        except Exception as e:
            log.exception("relay %s: %s", provider, e)
            self._send_json(502, {"error": str(e)})


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", PORT), RelayHandler)
    log.info("llm_relay on :%s providers=%s secret=%s", PORT, UPSTREAM, "on" if SECRET else "off")
    server.serve_forever()


if __name__ == "__main__":
    main()
