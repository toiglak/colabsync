"""Command-line entry point for ColabSync."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import click

from colabsync.client import run_client


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.option(
    "--session",
    "session_name",
    required=True,
    help="Colab CLI session to synchronize with.",
)
@click.option(
    "--root",
    default=".",
    show_default=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Local repository root to sync.",
)
@click.option(
    "--identity",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="SSH private/public key for the Colab CLI, when no agent is available.",
)
def main(session_name: str, root: Path, identity: Path | None) -> None:
    """Synchronize local files into a running Google Colab session."""
    if shutil.which("colab") is None:
        raise click.ClickException(
            "Colab CLI not found. Install it with `uv tool install google-colab-cli`."
        )

    try:
        if identity is None:
            asyncio.run(run_client(root.resolve(), session_name))
        else:
            asyncio.run(run_client(root.resolve(), session_name, str(identity)))
    except KeyboardInterrupt:
        click.echo("colabsync stopped")
