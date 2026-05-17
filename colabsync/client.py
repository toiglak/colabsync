"""
Local-side sync engine.

Connects to the Colab server via WebSocket (over a Cloudflare tunnel),
authenticates with the shared secret, performs an initial full sync, and then
watches the repository for changes using watchfiles.
"""

from __future__ import annotations

import asyncio
import hmac
from pathlib import Path

import websockets
from rich.console import Console
from watchfiles import awatch, Change

from colabsync.filter import FileFilter
from colabsync import protocol

console = Console(stderr=True)

PING_INTERVAL = 20  # seconds
RECONNECT_INITIAL_DELAY = 2.0
RECONNECT_MAX_DELAY = 60.0
RECONNECT_FACTOR = 2.0
MAX_RECONNECT_ATTEMPTS = 5
MAX_MSG_SIZE = 10 * 1024 * 1024  # 10 MB


async def run_client(root: Path, tunnel_url: str, secret: bytes) -> None:
    """
    Main entry-point for the local client.

    Runs until cancelled (Ctrl-C) or until reconnection fails repeatedly.
    """
    ws_url = tunnel_url.replace("http://", "ws://").replace("https://", "wss://")
    filt = FileFilter(root)

    console.print(f"[bold]colabsync[/bold]  root  [cyan]{root}[/cyan]")
    console.print(f"[bold]colabsync[/bold]  remote [cyan]{ws_url}[/cyan]")

    delay = RECONNECT_INITIAL_DELAY
    attempts = 0

    while True:
        try:
            await _connect_and_watch(ws_url, secret, root, filt)
            # If we were watching and the connection closed gracefully, 
            # or if it was established successfully then dropped:
            delay = RECONNECT_INITIAL_DELAY
            attempts = 0
        except websockets.ConnectionClosedOK:
            console.print("[yellow]colabsync server has shut down gracefully (Colab session stopped or stop command run). Stopping client.[/yellow]")
            return
        except (
            websockets.ConnectionClosed,
            websockets.WebSocketException,
            OSError,
        ) as exc:
            attempts += 1
            if attempts > MAX_RECONNECT_ATTEMPTS:
                console.print(f"[red]error[/red] connection lost and exceeded maximum retries ({MAX_RECONNECT_ATTEMPTS}). giving up.")
                return

            console.print(
                f"[red]connection lost[/red] ({exc}) – retrying in {delay:.1f}s "
                f"(attempt {attempts}/{MAX_RECONNECT_ATTEMPTS})"
            )
            await asyncio.sleep(delay)
            delay = min(delay * RECONNECT_FACTOR, RECONNECT_MAX_DELAY)
        except asyncio.CancelledError:
            console.print("[dim]colabsync stopped[/dim]")
            return


async def _connect_and_watch(
    ws_url: str,
    secret: bytes,
    root: Path,
    filt: FileFilter,
) -> None:
    async with websockets.connect(
        ws_url,
        ping_interval=PING_INTERVAL,
        ping_timeout=10,
        open_timeout=15,
        max_size=MAX_MSG_SIZE,
    ) as ws:
        # --- Authenticate ---
        await ws.send(protocol.auth_msg(secret))
        raw = await asyncio.wait_for(ws.recv(), timeout=10)
        reply = protocol.parse(raw)
        if reply.get("type") != "ok":
            raise RuntimeError(f"Auth rejected: {reply.get('message', 'unknown')}")

        console.print("[green]connected[/green]  performing initial sync…")

        # --- Initial full sync ---
        await _initial_sync(ws, root, filt)
        console.print("[green]ready[/green]  watching for changes")

        # --- Watch for changes ---
        async def watch_loop():
            async for changes in awatch(root, recursive=True):
                # Refresh ignore matchers if a ignore-file itself changed
                if _any_ignore_file_changed(changes):
                    filt.refresh()

                for change_type, path_str in changes:
                    path = Path(path_str)

                    # Skip the .git directory entirely
                    if ".git" in path.parts:
                        continue

                    if change_type == Change.deleted:
                        # Send delete regardless of filters (the file was already there)
                        try:
                            rel = path.relative_to(root).as_posix()
                            await ws.send(protocol.delete_msg(root, path))
                            console.print(f"[red]del[/red]    [dim]{rel}[/dim]")
                        except ValueError:
                            pass
                    else:
                        # Added or modified
                        if not path.is_file():
                            continue
                        if not filt.should_sync(path):
                            continue
                        try:
                            rel = path.relative_to(root).as_posix()
                            await ws.send(protocol.put_msg(root, path))
                            verb = "add" if change_type == Change.added else "upd"
                            console.print(f"[cyan]{verb}[/cyan]    [dim]{rel}[/dim]")
                        except (ValueError, OSError):
                            pass

        watch_task = asyncio.create_task(watch_loop())
        close_task = asyncio.create_task(ws.wait_closed())

        done, pending = await asyncio.wait(
            [watch_task, close_task],
            return_when=asyncio.FIRST_COMPLETED
        )

        for task in pending:
            task.cancel()

        if close_task.done():
            raise ws.connection_closed_exc()
        elif watch_task.done():
            await watch_task


async def _initial_sync(ws, root: Path, filt: FileFilter) -> None:
    """Walk the tree and push files in batches."""
    batch_msgs = []
    batch_bytes = 0
    total_sent = 0
    
    # Limits for batching
    MAX_BATCH_SIZE = 5 * 1024 * 1024  # 5 MB
    MAX_BATCH_COUNT = 100

    for dirpath, dirnames, filenames in (root).walk():
        dirnames[:] = [
            d for d in dirnames
            if d != ".git" and filt.should_sync_dir(Path(dirpath) / d)
        ]
        
        for fname in filenames:
            path = Path(dirpath) / fname
            if filt.should_sync(path):
                try:
                    msg = protocol.put_msg(root, path)
                    batch_msgs.append(msg)
                    batch_bytes += len(msg)
                    total_sent += 1
                    
                    if batch_bytes >= MAX_BATCH_SIZE or len(batch_msgs) >= MAX_BATCH_COUNT:
                        await ws.send(protocol.batch_msg(batch_msgs))
                        batch_msgs = []
                        batch_bytes = 0
                except OSError:
                    pass

    # Final batch
    if batch_msgs:
        await ws.send(protocol.batch_msg(batch_msgs))

    console.print(f"[dim]initial sync: {total_sent} file(s)[/dim]")


def _any_ignore_file_changed(changes) -> bool:
    ignore_names = {".gitignore", ".colabignore"}
    return any(Path(p).name in ignore_names for _, p in changes)
