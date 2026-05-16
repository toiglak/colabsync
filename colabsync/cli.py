"""
CLI entry-point for colabsync.

Usage:
    colabsync start [--port PORT] [--dest DIR]
    colabsync stop
    colabsync join <join-link> [--root DIR]
"""

from __future__ import annotations

import asyncio
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

import click
from rich.console import Console

from colabsync import link as link_module
from colabsync.client import run_client
from colabsync.server import ColabServer

console = Console(stderr=True)

PID_FILE = Path("/tmp/colabsync.pid")
LINK_FILE = Path("/tmp/colabsync.link")
STATUS_FILE = Path("/tmp/colabsync.status")


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
@click.option("--_daemon", is_flag=True, hidden=True)
def start(port: int, dest: Path, force: bool, _daemon: bool) -> None:
    """Start the colabsync server (Colab side)."""
    if not _daemon:
        _start_background(port, dest, force)
        return

    # 1. Environment check
    in_colab = _is_colab()
    if not in_colab and not force:
        console.print("[red]error[/red] Not in Colab environment. Use [bold]--force[/bold] to override.")
        sys.exit(1)

    # Check if already running
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text())
            os.kill(pid, 0)
            console.print(f"[yellow]colabsync is already running (PID {pid}).[/yellow]")
            _print_join_link_if_exists(header=False)
            console.print("Use [bold]colabsync stop[/bold] first if you want to restart.")
            sys.exit(1)
        except (ProcessLookupError, ValueError):
            PID_FILE.unlink(missing_ok=True)

    # 2. Install cloudflared if in Colab
    if in_colab:
        _install_cloudflared()

    # 2. Setup secret
    secret = link_module.generate_secret()

    # 3. Start server in background
    dest.mkdir(parents=True, exist_ok=True)
    srv = ColabServer(dest_root=dest, secret=secret, port=port)
    
    # We need to run the server and the tunnel concurrently
    async def run_all():
        PID_FILE.write_text(str(os.getpid()))
        LINK_FILE.unlink(missing_ok=True)
        STATUS_FILE.unlink(missing_ok=True)
        
        server_task = asyncio.create_task(srv.serve())
        
        tunnel_proc = None
        try:
            # 4. Start Tunnel
            tunnel_url, tunnel_proc = await _start_tunnel(port)
            
            # 5. Print Join Link
            join_link = link_module.encode(tunnel_url, secret)
            LINK_FILE.write_text(join_link)
            
            console.print(f"\n[bold green]colabsync is ready![/bold green]")
            console.print(f"Run locally: [bold]colabsync join {join_link}[/bold]\n")
            
            await server_task
        finally:
            if tunnel_proc:
                tunnel_proc.terminate()
                await tunnel_proc.wait()
            PID_FILE.unlink(missing_ok=True)
            LINK_FILE.unlink(missing_ok=True)
            STATUS_FILE.unlink(missing_ok=True)

    try:
        asyncio.run(run_all())
    except KeyboardInterrupt:
        pass


@main.command()
def stop() -> None:
    """Stop a running colabsync server."""
    if not PID_FILE.exists():
        console.print("[yellow]colabsync is not running.[/yellow]")
        return

    try:
        pid = int(PID_FILE.read_text())
        os.kill(pid, signal.SIGTERM)
        console.print(f"[green]Stopped colabsync (PID {pid})[/green]")
    except (ProcessLookupError, ValueError):
        console.print("[yellow]colabsync was not running (stale PID file).[/yellow]")
    except OSError as e:
        console.print(f"[red]Error stopping colabsync: {e}[/red]")
    
    PID_FILE.unlink(missing_ok=True)
    LINK_FILE.unlink(missing_ok=True)
    STATUS_FILE.unlink(missing_ok=True)


def _start_background(port: int, dest: Path, force: bool) -> None:
    # Check if already running
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text())
            os.kill(pid, 0)
            console.print(f"[yellow]colabsync is already running (PID {pid}).[/yellow]")
            _print_join_link_if_exists(header=False)
            return
        except (ProcessLookupError, ValueError):
            PID_FILE.unlink(missing_ok=True)

    LINK_FILE.unlink(missing_ok=True)
    STATUS_FILE.unlink(missing_ok=True)

    if _is_colab():
        _install_cloudflared()
    # Construct command to run in foreground in the background process
    cmd = [sys.executable, "-m", "colabsync.cli", "start", "--port", str(port), "--dest", str(dest), "--_daemon"]
    if force:
        cmd.append("--force")
    
    with console.status("preparing tunnel...", spinner="dots"):
        subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True
        )
        
        # Wait for the link file to appear
        for _ in range(60):
            if LINK_FILE.exists():
                break
            time.sleep(1)
    
    # Now that the spinner is gone, print the final message
    if not _print_join_link_if_exists(header=True):
        console.print("[red]timed out waiting for colabsync to start in background.[/red]")
        console.print("check /tmp/tunnel.log if cloudflared is failing.")
    
    STATUS_FILE.unlink(missing_ok=True)


def _print_join_link_if_exists(header: bool = True) -> bool:
    """Read the link file and print the join command if present."""
    if LINK_FILE.exists():
        try:
            link = LINK_FILE.read_text().strip()
            if link:
                if header:
                    console.print(f"\n[bold green]colabsync is ready![/bold green]")
                    console.print(f"Run locally: [bold]colabsync join {link}[/bold]\n")
                else:
                    console.print(f"Run locally: [bold]colabsync join {link}[/bold]")
                return True
        except Exception:
            pass
    return False


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
    if subprocess.run(["which", "cloudflared"], capture_output=True).returncode == 0:
        return

    commands = [
        "sudo mkdir -p --mode=0755 /usr/share/keyrings",
        "curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null",
        "echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main' | sudo tee /etc/apt/sources.list.d/cloudflared.list",
        "sudo apt-get update -qq",
        "sudo apt-get install -y -qq cloudflared"
    ]
    for cmd in commands:
        subprocess.run(cmd, shell=True, check=True, capture_output=True)


async def _start_tunnel(port: int) -> tuple[str, asyncio.subprocess.Process]:
    STATUS_FILE.write_text("opening tunnel...")
    log_file = open("/tmp/tunnel.log", "w")
    proc = await asyncio.create_subprocess_shell(
        f"cloudflared tunnel --url http://localhost:{port}",
        stdout=log_file,
        stderr=log_file,
        start_new_session=True
    )
    
    for _ in range(30):
        await asyncio.sleep(1)
        try:
            with open("/tmp/tunnel.log", "r") as f:
                content = f.read()
                match = re.search(r"https://[a-z0-9\-]+\.trycloudflare\.com", content)
                if match:
                    return match.group(0), proc
        except Exception:
            pass
    
    # If we got here, it failed. Print logs for debugging.
    if proc:
        proc.terminate()
        await proc.wait()
    try:
        with open("/tmp/tunnel.log", "r") as f:
            console.print(f"[red]Tunnel Logs:[/red]\n{f.read()}")
    except Exception:
        pass
    
    raise RuntimeError("Failed to start cloudflared tunnel (timed out waiting for URL)")


if __name__ == "__main__":
    main()
