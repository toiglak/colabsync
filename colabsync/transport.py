"""One-shot Colab SSH transport for synchronization batches."""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal

REMOTE_ROOT = "/content"


@dataclass(frozen=True, slots=True)
class SyncOperation:
    """A single remote file operation."""

    kind: Literal["write", "delete"]
    path: str
    data: bytes | None = None

    def __post_init__(self) -> None:
        if self.kind not in {"write", "delete"}:
            raise ValueError(f"Unknown sync operation: {self.kind!r}")
        _validate_relative_path(self.path)
        if self.kind == "write" and self.data is None:
            raise ValueError("Write operations require file data")
        if self.kind == "delete" and self.data is not None:
            raise ValueError("Delete operations cannot contain file data")

    @classmethod
    def write(cls, path: str, data: bytes) -> "SyncOperation":
        return cls("write", path, data)

    @classmethod
    def delete(cls, path: str) -> "SyncOperation":
        return cls("delete", path)


class TransferError(RuntimeError):
    """Raised when a Colab SSH batch exits unsuccessfully."""


def build_script(
    operations: list[SyncOperation],
    *,
    remote_root: str = REMOTE_ROOT,
) -> str:
    """Build a self-contained Python script for one synchronization batch."""
    payload = []
    for operation in operations:
        item = {"kind": operation.kind, "path": operation.path}
        if operation.kind == "write":
            assert operation.data is not None
            item["data"] = base64.b64encode(operation.data).decode("ascii")
        payload.append(item)

    # repr() produces a Python literal while safely escaping paths and data.
    # The payload contains no executable code derived from the local files.
    return f"""from base64 import b64decode
from pathlib import Path

ROOT = Path({remote_root!r}).resolve()
OPERATIONS = {payload!r}

for operation in OPERATIONS:
    destination = (ROOT / operation[\"path\"]).resolve()
    if not destination.is_relative_to(ROOT):
        raise RuntimeError(f\"Path traversal: {{operation['path']!r}}\")

    if operation[\"kind\"] == \"write\":
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b64decode(operation[\"data\"], validate=True))
    elif operation[\"kind\"] == \"delete\":
        # Never remove directories: they may contain runtime-generated files.
        if destination.is_file() or destination.is_symlink():
            destination.unlink()
    else:
        raise RuntimeError(f\"Unknown sync operation: {{operation['kind']!r}}\")
"""


class ColabTransport:
    """Send synchronization batches through the local Colab CLI."""

    def __init__(self, session: str, identity: str | None = None) -> None:
        self.session = session
        self.identity = identity

    async def send(self, operations: list[SyncOperation]) -> None:
        script = build_script(operations)
        try:
            command = ["colab", "ssh", "-s", self.session]
            if self.identity:
                command.extend(["--identity", self.identity])
            command.extend(["--", "python3"])
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate(script.encode("utf-8"))
        except OSError as exc:
            raise TransferError(f"could not start colab ssh: {exc}") from exc

        if process.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace").strip()
            if not detail:
                detail = stdout.decode("utf-8", errors="replace").strip()
            if not detail:
                detail = f"exit status {process.returncode}"
            raise TransferError(detail)


def _validate_relative_path(path: str) -> None:
    parsed = PurePosixPath(path)
    if not path or parsed.is_absolute() or ".." in parsed.parts or "." in parsed.parts:
        raise ValueError(f"Sync path must be relative to the repository root: {path!r}")
