"""tests/test_aiangelcomfypod.py — minimal birth test (must pass at scaffold time)."""
from pathlib import Path
import tempfile

import pytest

# Import the package to verify it is importable
import aiangelcomfypod


def test_version_string():
    """Package must expose __version__."""
    assert isinstance(aiangelcomfypod.__version__, str)
    assert aiangelcomfypod.__version__  # non-empty


def test_msg_file_roundtrip(tmp_path: Path):
    """example.main() must process a msg-file and write output."""
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    msg = tmp_path / "input.txt"
    msg.write_text("hello world", encoding="utf-8")
    out = tmp_path / "output.txt"

    from aiangelcomfypod.example import main
    import unittest.mock as mock

    with mock.patch("sys.argv", ["prog", "--msg-file", str(msg), "--output", str(out)]):
        rc = main()

    assert rc == 0
    assert out.exists()
    assert "hello world" in out.read_text(encoding="utf-8")
