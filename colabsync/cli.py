"""
CLI entry-point for colabsync.

Usage:
    colabsync <join-link>             # watch current dir, sync to Colab
    colabsync <join-link> --root DIR  # watch a specific directory
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import click
from rich.console import Console

from colabsync import link as link_module
from colabsync.client import run_client

console = Console(stderr=True)


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.argument("join_link")
@click.option(
    "--root",
    default=".",
    show_default=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Local repository root to sync. Defaults to the current directory.",
)
def main(join_link: str, root: Path) -> None:
    """
    Sync a local repository into a running Google Colab session.

    JOIN_LINK is the link printed by the colab-hook script in the Colab notebook.
    """
    try:
        tunnel_url, secret = link_module.decode(join_link)
    except ValueError as exc:
        console.print(f"[red]error[/red] {exc}")
        sys.exit(1)

    try:
        asyncio.run(run_client(root.resolve(), tunnel_url, secret))
    except KeyboardInterrupt:
        pass
