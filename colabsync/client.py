"""Local file watcher and serialized Colab synchronization engine."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Awaitable, Callable

from rich.console import Console
from watchfiles import Change, awatch

from colabsync.filter import FileFilter
from colabsync.transport import ColabTransport, SyncOperation, TransferError

console = Console(stderr=True)

RECONNECT_INITIAL_DELAY = 2.0
RECONNECT_MAX_DELAY = 30.0
RECONNECT_FACTOR = 2.0
MAX_BATCH_BYTES = 5 * 1024 * 1024
MAX_BATCH_COUNT = 100
WATCH_BATCH_DELAY = 0.05

ChangeSet = list[tuple[Change, str]]
Sleep = Callable[[float], Awaitable[None]]


class SyncEngine:
    """Watch a repository and send serialized batches to a Colab session."""

    def __init__(
        self,
        root: Path,
        transport,
        filt: FileFilter | None = None,
        *,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self.root = root.resolve()
        self.transport = transport
        self.filt = filt or FileFilter(self.root)
        self.sleep = sleep
        self._changes: asyncio.Queue[ChangeSet] = asyncio.Queue()
        self._owned_paths: set[str] = set()

    async def run(self) -> None:
        """Perform the initial sync, then watch until cancelled."""
        watcher_task = asyncio.create_task(self._watch())
        worker_task: asyncio.Task | None = None
        try:
            # Let watchfiles establish its native watcher before taking the
            # initial snapshot. Changes during the snapshot or transfer stay
            # in the queue and are applied afterward.
            await asyncio.sleep(0)
            console.print("[cyan]syncing[/cyan] initial repository snapshot…")
            await self._full_reconciliation(reason="initial")
            console.print("[green]ready[/green] watching for changes")

            worker_task = asyncio.create_task(self._worker())
            done, pending = await asyncio.wait(
                [watcher_task, worker_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            for task in done:
                await task
        finally:
            watcher_task.cancel()
            if worker_task is not None:
                worker_task.cancel()
            await asyncio.gather(watcher_task, worker_task, return_exceptions=True)

    async def _watch(self) -> None:
        async for changes in awatch(self.root, recursive=True):
            change_set = list(changes)
            if _any_ignore_file_changed(change_set):
                self.filt.refresh()
            await self._changes.put(change_set)

    async def _worker(self) -> None:
        while True:
            changes = await self._next_change_batch()
            operations = self._build_change_operations(changes)
            if operations:
                await self._send_change_operations(operations)

    async def _next_change_batch(self) -> ChangeSet:
        changes = await self._changes.get()
        if WATCH_BATCH_DELAY <= 0:
            return changes

        deadline = asyncio.get_running_loop().time() + WATCH_BATCH_DELAY
        combined = list(changes)
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return combined
            try:
                combined.extend(await asyncio.wait_for(self._changes.get(), remaining))
            except asyncio.TimeoutError:
                return combined

    def _build_full_operations(self) -> list[SyncOperation]:
        operations: list[SyncOperation] = []
        current_paths: set[str] = set()

        for dirpath, dirnames, filenames in self.root.walk():
            dirnames[:] = [
                directory
                for directory in dirnames
                if directory != ".git"
                and self.filt.should_sync_dir(Path(dirpath) / directory)
            ]

            for filename in filenames:
                path = Path(dirpath) / filename
                if not self.filt.should_sync(path):
                    continue
                try:
                    rel = path.relative_to(self.root).as_posix()
                    data = path.read_bytes()
                except (OSError, ValueError):
                    continue
                operations.append(SyncOperation.write(rel, data))
                current_paths.add(rel)

        for rel in sorted(self._owned_paths - current_paths):
            path = self.root / rel
            if self.filt.should_sync_deleted(path):
                operations.append(SyncOperation.delete(rel))

        return operations

    def _build_change_operations(self, changes: ChangeSet) -> list[SyncOperation]:
        paths: dict[str, Path] = {}
        for _, path_str in changes:
            path = Path(path_str)
            try:
                rel = path.relative_to(self.root).as_posix()
            except ValueError:
                continue
            if ".git" in Path(rel).parts:
                continue
            paths[rel] = path

        operations: list[SyncOperation] = []
        for rel, path in sorted(paths.items()):
            if path.is_file():
                if not self.filt.should_sync(path):
                    continue
                try:
                    operations.append(SyncOperation.write(rel, path.read_bytes()))
                except OSError:
                    continue
            elif not path.exists() and rel in self._owned_paths:
                # A deleted ignored path is intentionally left on the remote.
                if self.filt.should_sync_deleted(path):
                    operations.append(SyncOperation.delete(rel))

        return operations

    async def _send_change_operations(self, operations: list[SyncOperation]) -> None:
        for batch in _iter_batches(operations):
            recovered = await self._send_with_retry(batch)
            self._commit(batch)
            _report_batch(batch)
            if recovered:
                await self._full_reconciliation(reason="reconnected")
                return

    async def _full_reconciliation(self, *, reason: str = "initial") -> None:
        """Synchronize the current snapshot, restarting after reconnection."""
        while True:
            operations = self._build_full_operations()
            batches = list(_iter_batches(operations)) or [[]]
            reconnected = False

            for batch in batches:
                recovered = await self._send_with_retry(batch)
                self._commit(batch)
                _report_batch(batch)
                if recovered:
                    reconnected = True
                    console.print(
                        "[yellow]reconnected[/yellow] rebuilding the current snapshot…"
                    )
                    break

            if not reconnected:
                label = "initial sync" if reason == "initial" else "reconciliation"
                console.print(
                    f"[dim]{label}: "
                    f"{sum(operation.kind == 'write' for operation in operations)} file(s)[/dim]"
                )
                return

    async def _send_with_retry(self, batch: list[SyncOperation]) -> bool:
        delay = RECONNECT_INITIAL_DELAY
        attempts = 0
        while True:
            try:
                await self.transport.send(batch)
            except (OSError, TransferError) as exc:
                attempts += 1
                console.print(
                    f"[red]connection lost[/red] ({exc}) – "
                    f"retrying in {delay:.1f}s (attempt {attempts})"
                )
                await self.sleep(delay)
                delay = min(delay * RECONNECT_FACTOR, RECONNECT_MAX_DELAY)
            else:
                if attempts:
                    console.print("[green]connection restored[/green] batch transferred")
                return attempts > 0

    def _commit(self, operations: list[SyncOperation]) -> None:
        for operation in operations:
            if operation.kind == "write":
                self._owned_paths.add(operation.path)
            else:
                self._owned_paths.discard(operation.path)


async def run_client(root: Path, session: str, identity: str | None = None) -> None:
    """Run ColabSync until Ctrl-C or cancellation."""
    root = root.resolve()
    console.print(f"[bold]colabsync[/bold] root [cyan]{root}[/cyan]")
    console.print(f"[bold]colabsync[/bold] session [cyan]{session}[/cyan]")
    try:
        await SyncEngine(root, ColabTransport(session, identity=identity)).run()
    except asyncio.CancelledError:
        console.print("[dim]colabsync stopped[/dim]")


def _iter_batches(operations: list[SyncOperation]):
    batch: list[SyncOperation] = []
    batch_bytes = 0
    for operation in operations:
        operation_bytes = len(operation.path.encode("utf-8")) + 64
        if operation.data is not None:
            operation_bytes += len(operation.data)

        if batch and (
            batch_bytes + operation_bytes > MAX_BATCH_BYTES
            or len(batch) >= MAX_BATCH_COUNT
        ):
            yield batch
            batch = []
            batch_bytes = 0

        batch.append(operation)
        batch_bytes += operation_bytes

    if batch:
        yield batch


def _report_batch(batch: list[SyncOperation]) -> None:
    writes = sum(operation.kind == "write" for operation in batch)
    deletes = len(batch) - writes
    details = []
    if writes:
        details.append(f"{writes} write(s)")
    if deletes:
        details.append(f"{deletes} deletion(s)")
    if details:
        console.print(f"[green]synced[/green] {', '.join(details)}")


def _any_ignore_file_changed(changes: ChangeSet) -> bool:
    ignore_names = {".gitignore", ".colabignore"}
    return any(Path(path).name in ignore_names for _, path in changes)
