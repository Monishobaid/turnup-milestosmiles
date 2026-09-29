"""Dependency-light authenticated HTTP API for TURNUP scheduling."""

from __future__ import annotations

import hmac
import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .connectors import connector_for
from .solver import solve_schedule


class TurnupHandler(BaseHTTPRequestHandler):
    server_version = "TURNUP/0.2"

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        configured = os.getenv("TURNUP_API_TOKEN")
        if not configured:
            return False
        supplied = self.headers.get("Authorization", "")
        return hmac.compare_digest(supplied, f"Bearer {configured}")

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 2_000_000:
            raise ValueError("request body must be between 1 byte and 2 MB")
        payload = json.loads(self.rfile.read(length))
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        return payload

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._json(HTTPStatus.OK, {"status": "ok", "service": "turnup-api"})
            return
        if not self._authorized():
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "missing or invalid bearer token"})
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorized():
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "missing or invalid bearer token"})
            return
        try:
            payload = self._body()
            if self.path == "/v1/schedule":
                result = solve_schedule(payload["intervals"], payload["jobs"], float(payload["site_capacity_mw"]))
                self._json(HTTPStatus.OK, {"status": result.status, "objective": result.objective, "assignments": result.assignments, "summary": result.summary})
                return
            if self.path == "/v1/dispatch":
                connector = connector_for(str(payload.get("connector", "dry-run")))
                receipt = connector.dispatch(payload.get("assignments", []))
                self._json(HTTPStatus.OK, receipt.__dict__)
                return
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        except (KeyError, TypeError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def log_message(self, format: str, *args: Any) -> None:
        return


def serve(host: str = "127.0.0.1", port: int = 8090) -> None:
    if not os.getenv("TURNUP_API_TOKEN"):
        raise RuntimeError("TURNUP_API_TOKEN must be set; the API will not start unauthenticated")
    server = ThreadingHTTPServer((host, port), TurnupHandler)
    print(f"TURNUP API listening on http://{host}:{port}")
    server.serve_forever()
