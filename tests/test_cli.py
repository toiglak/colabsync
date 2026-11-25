from unittest import mock

from click.testing import CliRunner

from colabsync.cli import main


def test_session_is_required():
    result = CliRunner().invoke(main, [])

    assert result.exit_code == 2
    assert "Missing option" in result.output
    assert "--session" in result.output


def test_cli_runs_sync_for_selected_session(tmp_path):
    with mock.patch("colabsync.cli.shutil.which", return_value="/usr/local/bin/colab"), \
        mock.patch("colabsync.cli.run_client", new_callable=mock.AsyncMock) as run:
        result = CliRunner().invoke(main, ["--session", "dev", "--root", str(tmp_path)])

    assert result.exit_code == 0
    run.assert_awaited_once_with(tmp_path.resolve(), "dev")
