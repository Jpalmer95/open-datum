"""PLE Competition Entrypoint (`serve.py`).

Supports two modes for container harnesses (*Harbor*, *Archipelago*, or local agents):
  - `--stdio` (default): JSON-RPC 2.0 MCP server over stdin/stdout (zero network required)
  - `--http --port 8080`: Localhost HTTP JSON-RPC 2.0 + `/health` endpoint inside the container
"""

from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "python"))
sys.path.insert(0, str(REPO_ROOT))

from opendatum.mcp_server import OpenDatumMCPServer


def run_http(host: str, port: int) -> None:
    mcp = OpenDatumMCPServer()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/health":
                body = json.dumps({"status": "ok", "server": "opendatum-ple-harness", "tools": len(mcp.tools)}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8")
            try:
                req = json.loads(raw)
                resp = mcp.handle_request(req) or {"jsonrpc": "2.0", "result": {"ok": True}}
                code = 200
            except Exception as exc:
                resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(exc)}}
                code = 400
            body = json.dumps(resp).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            return

    server = HTTPServer((host, port), Handler)
    print(f"OpenDatum PLE Harness listening on http://{host}:{port} ({len(mcp.tools)} tools)", flush=True)
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenDatum PLE Agent Harness Server")
    parser.add_argument("--http", action="store_true", help="Serve HTTP JSON-RPC instead of stdio MCP")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    if args.http:
        run_http(args.host, args.port)
    else:
        OpenDatumMCPServer().serve_stdio()


if __name__ == "__main__":
    main()
