"""
Server-side CLI entrypoint (runs inside Colab).

Reads the shared secret from the COLABSYNC_SECRET environment variable.

Usage:
    colabsync-server [--port PORT] [--dest DIR]
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import click
from rich.console import Console

from colabsync.server import ColabServer

console = Console(stderr=True)


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.option("--port", default=8765, show_default=True, help="Port to listen on.")
@click.option(
    "--dest",
    default="/content",
    show_default=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Directory to write synced files into.",
)
def server_main(port: int, dest: Path) -> None:
    """
    Start the colabsync WebSocket server (Colab side).

    The shared secret must be provided via the COLABSYNC_SECRET environment variable.
    This is called automatically by scripts/colab-hook.sh.
    """
    secret_hex = os.environ.get("COLABSYNC_SECRET", "")
    if not secret_hex:
        console.print("[red]error[/red] COLABSYNC_SECRET environment variable is not set.")
        sys.exit(1)

    try:
        secret = bytes.fromhex(secret_hex)
    except ValueError:
        console.print("[red]error[/red] COLABSYNC_SECRET is not valid hex.")
        sys.exit(1)

    dest.mkdir(parents=True, exist_ok=True)
    srv = ColabServer(dest_root=dest, secret=secret, port=port)

    try:
        asyncio.run(srv.serve())
    except KeyboardInterrupt:
        pass
