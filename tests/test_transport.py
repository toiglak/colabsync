import asyncio
import base64
from unittest.mock import AsyncMock, patch

import pytest

from colabsync.transport import ColabTransport, SyncOperation, TransferError, build_script


def test_build_script_applies_text_binary_and_delete_operations(tmp_path):
    text_path = tmp_path / "text.txt"
    binary_path = tmp_path / "data.bin"
    remove_path = tmp_path / "remove.txt"
    text_path.write_text("old")
    binary_path.write_bytes(b"old")
    remove_path.write_text("remove me")

    script = build_script(
        [
            SyncOperation.write("text.txt", b"hello"),
            SyncOperation.write("data.bin", bytes(range(256))),
            SyncOperation.delete("remove.txt"),
        ],
        remote_root=str(tmp_path),
    )

    exec(script, {})

    assert text_path.read_bytes() == b"hello"
    assert binary_path.read_bytes() == bytes(range(256))
    assert not remove_path.exists()
    assert base64.b64encode(bytes(range(256))).decode() in script


def test_build_script_rejects_paths_outside_remote_root(tmp_path):
    with pytest.raises(ValueError, match="must be relative"):
        SyncOperation.write("../outside.txt", b"nope")


@pytest.mark.asyncio
async def test_transport_pipes_each_batch_to_colab_ssh(tmp_path):
    process = AsyncMock()
    process.returncode = 0
    process.communicate.return_value = (b"", b"")

    with patch("colabsync.transport.asyncio.create_subprocess_exec", new_callable=AsyncMock) as run:
        run.return_value = process
        await ColabTransport("dev").send([SyncOperation.write("x.bin", b"\x00\xff")])

    run.assert_awaited_once_with(
        "colab",
        "ssh",
        "-s",
        "dev",
        "--",
        "python3",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    script = process.communicate.await_args.args[0].decode()
    assert "x.bin" in script
    assert base64.b64encode(b"\x00\xff").decode() in script


@pytest.mark.asyncio
async def test_transport_raises_on_failed_remote_command():
    process = AsyncMock()
    process.returncode = 1
    process.communicate.return_value = (b"", b"remote failure")

    with patch("colabsync.transport.asyncio.create_subprocess_exec", new_callable=AsyncMock) as run:
        run.return_value = process
        with pytest.raises(TransferError, match="remote failure"):
            await ColabTransport("dev").send([])


@pytest.mark.asyncio
async def test_transport_can_forward_an_ssh_identity():
    process = AsyncMock()
    process.returncode = 0
    process.communicate.return_value = (b"", b"")

    with patch("colabsync.transport.asyncio.create_subprocess_exec", new_callable=AsyncMock) as run:
        run.return_value = process
        await ColabTransport("dev", identity="/tmp/key").send([])

    args = run.await_args.args
    assert args[:6] == ("colab", "ssh", "-s", "dev", "--identity", "/tmp/key")
    assert args[6:] == ("--", "python3")
