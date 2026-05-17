import pytest
from click.testing import CliRunner
from unittest import mock
from colabsync.cli import main

def test_start_no_colab_no_force():
    runner = CliRunner()
    # Mock _is_colab to return False, mimicking local machine
    with mock.patch("colabsync.cli._is_colab", return_value=False):
        result = runner.invoke(main, ["start"])
        assert result.exit_code == 1
        assert "Not in Colab environment. Use --force to override." in result.output

def test_start_force_bypasses_colab_check():
    runner = CliRunner()
    # Mock _is_colab to return False, but pass --force
    # We mock _start_background so it doesn't actually try to run the daemon process
    with mock.patch("colabsync.cli._is_colab", return_value=False), \
         mock.patch("colabsync.cli._start_background") as mock_start_bg:
        result = runner.invoke(main, ["start", "--force"])
        assert result.exit_code == 0
        mock_start_bg.assert_called_once()
