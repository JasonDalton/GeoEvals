import pytest

from geoevals import __version__
from geoevals.cli import main


def test_version_is_dev_release() -> None:
    assert __version__ == "0.1.0"


def test_cli_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == "0.1.0"
