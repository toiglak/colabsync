"""
Colab-side WebSocket server.

This module is imported and called from the Colab hook script.  It:
  1. Starts a WebSocket server on localhost.
  2. Authenticates each incoming connection with the shared secret.
  3. Applies incoming file changes (put / delete) under *dest_root*.

The server is intended to be fronted by a Cloudflare tunnel (cloudflared),
which terminates TLS and forwards plain HTTP/WebSocket to localhost.
"""

from __future__ import annotations

import asyncio
import base64
import hmac
from pathlib import Path

import websockets
from rich.console import Console

from colabsync import protocol

console = Console(stderr=True)


class ColabServer:
    def __init__(self, dest_root: Path, secret: bytes, host: str = "127.0.0.1", port: int = 8765) -> None:
        self.dest_root = dest_root.resolve()
        self.secret = secret
        self.host = host
        self.port = port

    async def serve(self) -> None:
        console.print(
            f"[bold]colabsync server[/bold] listening on "
            f"[cyan]{self.host}:{self.port}[/cyan]  root=[cyan]{self.dest_root}[/cyan]"
        )
        async with websockets.serve(self._handler, self.host, self.port, max_size=10 * 1024 * 1024):
            await asyncio.get_event_loop().create_future()  # run forever

    async def _handler(self, ws) -> None:
        peer = ws.remote_address
        try:
            # --- Auth handshake ---
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=10)
            except asyncio.TimeoutError:
                await ws.send(protocol.error_msg("auth timeout"))
                return

            msg = protocol.parse(raw)
            if msg.get("type") != "auth":
                await ws.send(protocol.error_msg("expected auth message"))
                return

            incoming_secret_part = bytes.fromhex(msg.get("secret", ""))
            if not hmac.compare_digest(incoming_secret_part, self.secret[:2]):
                await ws.send(protocol.error_msg("invalid secret"))
                console.print(f"[red]rejected[/red] connection from {peer}")
                return

            await ws.send(protocol.ok_msg(self.secret))
            console.print(f"[green]accepted[/green] connection from {peer}")

            # --- Message loop ---
            async for raw in ws:
                try:
                    if isinstance(raw, bytes):
                        # Could be a single PUT or a BATCH
                        try:
                            # Try parsing as batch first
                            items = protocol.parse_batch(raw)
                            for itype, payload in items:
                                if itype == "put":
                                    self._handle_put(*payload)
                                elif itype == "json":
                                    self._handle_json_message(payload)
                        except ValueError:
                            # Fallback to single binary put
                            rel_path, data = protocol.parse_binary_put(raw)
                            self._handle_put(rel_path, data)
                    else:
                        self._handle_json_message(protocol.parse(raw))
                except ValueError as exc:
                    console.print(f"[yellow]warn[/yellow] bad message: {exc}")

        except websockets.ConnectionClosed:
            console.print(f"[dim]{peer} disconnected[/dim]")
        except Exception as exc:
            console.print(f"[red]error[/red] handler: {exc}")

    def _handle_put(self, rel_path: str, data: bytes) -> None:
        dest = self._safe_path(rel_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        console.print(f"[cyan]put[/cyan]    [dim]{rel_path}[/dim]")

    def _handle_json_message(self, msg: dict) -> None:
        mtype = msg.get("type")

        if mtype == "delete":
            rel_path = msg.get("path", "")
            dest = self._safe_path(rel_path)
            if dest.exists():
                dest.unlink()
                console.print(f"[red]del[/red]    [dim]{rel_path}[/dim]")

    def _safe_path(self, rel: str) -> Path:
        """Resolve *rel* under dest_root and ensure no path traversal."""
        dest = (self.dest_root / rel).resolve()
        if not dest.is_relative_to(self.dest_root):
            raise ValueError(f"Path traversal attempt: {rel!r}")
        return dest
