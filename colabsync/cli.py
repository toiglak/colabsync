"""
CLI entry-point for colabsync.

Usage:
    colabsync start [--port PORT] [--dest DIR]
    colabsync join <join-link> [--root DIR]
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import click
from rich.console import Console

from colabsync import link as link_module
from colabsync.client import run_client
from colabsync.server import ColabServer

console = Console(stderr=True)


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
def main() -> None:
    """Sync a local repository into a running Google Colab session."""
    pass


@main.command()
@click.argument("join_link")
@click.option(
    "--root",
    default=".",
    show_default=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Local repository root to sync.",
)
def join(join_link: str, root: Path) -> None:
    """Join a Colab session and start syncing."""
    try:
        tunnel_url, secret = link_module.decode(join_link)
    except ValueError as exc:
        console.print(f"[red]error[/red] {exc}")
        sys.exit(1)

    try:
        asyncio.run(run_client(root.resolve(), tunnel_url, secret))
    except KeyboardInterrupt:
        pass


@main.command()
@click.option("--port", default=8765, show_default=True, help="Port to listen on.")
@click.option(
    "--dest",
    default="/content",
    show_default=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Directory to write synced files into.",
)
@click.option("--force", is_flag=True, help="Force start even if not in Colab.")
def start(port: int, dest: Path, force: bool) -> None:
    """Start the colabsync server (Colab side)."""
    # 1. Environment check
    in_colab = _is_colab()
    if not in_colab and not force:
        console.print("[red]error[/red] Not in Colab environment. Use [bold]--force[/bold] to override.")
        sys.exit(1)

    # 2. Install cloudflared if in Colab
    if in_colab:
        _install_cloudflared()

    # 2. Setup secret
    secret = link_module.generate_secret()
    secret_hex = secret.hex()

    # 3. Start server in background
    dest.mkdir(parents=True, exist_ok=True)
    srv = ColabServer(dest_root=dest, secret=secret, port=port)
    
    # We need to run the server and the tunnel concurrently
    async def run_all():
        server_task = asyncio.create_task(srv.serve())
        
        # 4. Start Tunnel
        tunnel_url = await _start_tunnel(port)
        
        # 5. Print Join Link
        join_link = link_module.encode(tunnel_url, secret)
        console.print(f"\n[bold green]colabsync is ready![/bold green]")
        console.print(f"Run locally: [bold]colabsync join {join_link}[/bold]\n")
        
        await server_task

    try:
        asyncio.run(run_all())
    except KeyboardInterrupt:
        pass


def _is_colab() -> bool:
    """Fast check for Colab environment."""
    if os.getenv("COLAB_RELEASE_TAG"):
        return True
    try:
        import google.colab
        return True
    except ImportError:
        return False


def _install_cloudflared():
    if subprocess.run(["command", "-v", "cloudflared"], shell=True, capture_output=True).returncode == 0:
        return

    console.print("[dim]installing cloudflared...[/dim]")
    commands = [
        "sudo mkdir -p --mode=0755 /usr/share/keyrings",
        "curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null",
        "echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main' | sudo tee /etc/apt/sources.list.d/cloudflared.list",
        "sudo apt-get update -qq",
        "sudo apt-get install -y -qq cloudflared"
    ]
    for cmd in commands:
        subprocess.run(cmd, shell=True, check=True, capture_output=True)


async def _start_tunnel(port: int) -> str:
    console.print("[dim]opening tunnel...[/dim]")
    log_file = open("/tmp/tunnel.log", "w")
    proc = await asyncio.create_subprocess_shell(
        f"cloudflared tunnel --url http://localhost:{port}",
        stdout=log_file,
        stderr=log_file
    )
    
    for _ in range(30):
        await asyncio.sleep(1)
        try:
            with open("/tmp/tunnel.log", "r") as f:
                content = f.read()
                import re
                match = re.search(r"https://[a-z0-9\-]+\.trycloudflare\.com", content)
                if match:
                    return match.group(0)
        except Exception:
            pass
    
    raise RuntimeError("Failed to start cloudflared tunnel")
