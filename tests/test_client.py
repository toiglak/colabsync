import asyncio
from unittest import mock

import pytest
from watchfiles import Change

from colabsync.client import SyncEngine
from colabsync.transport import SyncOperation, TransferError


class RecordingTransport:
    def __init__(self, failures=0):
        self.calls = []
        self.failures = failures

    async def send(self, operations):
        self.calls.append(list(operations))
        if self.failures:
            self.failures -= 1
            raise TransferError("connection dropped")


def operation_paths(operations, kind):
    return {operation.path for operation in operations if operation.kind == kind}


def test_full_snapshot_only_writes_syncable_files_and_deletes_owned_files(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".gitignore").write_text("ignored.txt\n")
    (root / "keep.txt").write_text("keep")
    (root / "ignored.txt").write_text("do not sync")
    (root / "tracked.txt").write_text("tracked")

    engine = SyncEngine(root, RecordingTransport())
    engine._owned_paths.add("deleted.txt")
    engine._owned_paths.add("ignored.txt")

    operations = engine._build_full_operations()

    assert operation_paths(operations, "write") == {".gitignore", "keep.txt", "tracked.txt"}
    assert operation_paths(operations, "delete") == {"deleted.txt"}


def test_changes_preserve_ignored_and_remote_only_files(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".gitignore").write_text("ignored.txt\n")
    tracked = root / "tracked.txt"
    ignored = root / "ignored.txt"
    tracked.write_text("tracked")
    ignored.write_text("ignored")

    engine = SyncEngine(root, RecordingTransport())
    engine._owned_paths.update({"tracked.txt", "ignored.txt"})
    tracked.unlink()
    ignored.unlink()

    operations = engine._build_change_operations(
        [
            (Change.deleted, str(tracked)),
            (Change.deleted, str(ignored)),
            (Change.deleted, str(root / "remote-generated.txt")),
        ]
    )

    assert operations == [SyncOperation.delete("tracked.txt")]


@pytest.mark.asyncio
async def test_transfer_retries_and_reconciles_current_files(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "current.txt").write_text("current")
    transport = RecordingTransport(failures=1)
    engine = SyncEngine(root, transport, sleep=lambda _: asyncio.sleep(0))

    await engine._send_change_operations([SyncOperation.write("current.txt", b"changed")])

    assert len(transport.calls) >= 3
    assert transport.calls[0] == [SyncOperation.write("current.txt", b"changed")]
    assert transport.calls[1] == transport.calls[0]
    assert any(
        SyncOperation.write("current.txt", b"current") in call
        for call in transport.calls[2:]
    )


def test_batching_limits_each_batch_to_one_hundred_operations():
    from colabsync.client import _iter_batches

    operations = [SyncOperation.write(f"{index}.txt", b"data") for index in range(201)]

    batches = list(_iter_batches(operations))

    assert [len(batch) for batch in batches] == [100, 100, 1]


@pytest.mark.asyncio
async def test_changes_arriving_during_transfer_are_retained_and_serialized(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    first = root / "first.txt"
    second = root / "second.txt"
    first.write_text("first")
    second.write_text("second")

    transport = RecordingTransport()
    started = asyncio.Event()
    release = asyncio.Event()
    active = 0
    max_active = 0

    async def send(operations):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        transport.calls.append(list(operations))
        if len(transport.calls) == 1:
            started.set()
            await release.wait()
        active -= 1

    transport.send = send
    engine = SyncEngine(root, transport)

    with mock.patch("colabsync.client.WATCH_BATCH_DELAY", 0):
        worker = asyncio.create_task(engine._worker())
        await engine._changes.put([(Change.modified, str(first))])
        await started.wait()
        await engine._changes.put([(Change.modified, str(second))])
        release.set()
        await asyncio.wait_for(_wait_for_call_count(transport, 2), timeout=1)
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)

    assert max_active == 1
    assert transport.calls[0] == [SyncOperation.write("first.txt", b"first")]
    assert transport.calls[1] == [SyncOperation.write("second.txt", b"second")]


async def _wait_for_call_count(transport, count):
    while len(transport.calls) < count:
        await asyncio.sleep(0)
