"""`geoevals data inventory`: the license table in datasets/README.md."""

import shutil
from pathlib import Path

import pytest

from geoevals.cli import main
from geoevals.data.inventory import (
    END_MARKER,
    START_MARKER,
    InventoryError,
    inventory_rows,
    replace_table,
)

REPO = Path(__file__).parent.parent


def test_committed_inventory_is_up_to_date(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["data", "inventory", "--root", str(REPO), "--check"]) == 0
    assert "up to date" in capsys.readouterr().out


def test_inventory_has_one_row_per_asset_with_its_users() -> None:
    rows = {(row.dataset_id, row.asset_id): row for row in inventory_rows(REPO)}
    pilot = rows[("human_context_pilot", "osm_extract")]
    assert pilot.license == "ODbL-1.0"
    assert not pilot.redistributable
    assert pilot.used_by == (
        "`human_context_pilot` (pilot.yaml of benchmark `human_context_access`)",
    )
    assert rows[("smoke", "smoke_cases")].used_by == ("benchmark `smoke`",)
    places = rows[("gis_correctness", "places")]
    assert places.manifest == "benchmarks/gis_correctness/manifest.yaml"


def _copy_repo(tmp_path: Path) -> Path:
    for name in ("benchmarks", "datasets"):
        shutil.copytree(REPO / name, tmp_path / name, ignore=shutil.ignore_patterns("__pycache__"))
    return tmp_path


def test_check_fails_when_a_manifest_changes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _copy_repo(tmp_path)
    manifest = root / "benchmarks/smoke/manifest.yaml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(
            "attribution: GeoEvals contributors", "attribution: Someone else"
        ),
        encoding="utf-8",
    )
    assert main(["data", "inventory", "--root", str(root), "--check"]) == 1
    assert "out of date" in capsys.readouterr().err
    assert main(["data", "inventory", "--root", str(root)]) == 0
    assert "| Someone else |" in (root / "datasets/README.md").read_text(encoding="utf-8")
    assert main(["data", "inventory", "--root", str(root), "--check"]) == 0


def test_replace_table_keeps_the_rest_of_the_readme() -> None:
    text = f"# Title\n\nintro\n\n{START_MARKER}\nold\n{END_MARKER}\n\nafter\n"
    assert replace_table(text, "new\n") == (
        f"# Title\n\nintro\n\n{START_MARKER}\nnew\n{END_MARKER}\n\nafter\n"
    )


def test_replace_table_needs_the_markers() -> None:
    with pytest.raises(InventoryError):
        replace_table("# Title\n", "table\n")
    with pytest.raises(InventoryError):
        replace_table(f"{END_MARKER}\n{START_MARKER}\n", "table\n")
