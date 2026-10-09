import copy
import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from geoevals.cli import main
from geoevals.data.verify import sha256_file, verify_manifest
from geoevals.validation import (
    MANIFEST_SCHEMA_VERSION,
    Asset,
    DatasetManifest,
    SpecValidationError,
    detect_document_type,
    load_dataset_manifest,
    validate_manifest_document,
    validate_manifest_file,
)
from geoevals.validation.git import GitPathState, git_path_state
from geoevals.validation.validate import load_yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "schemas" / "dataset-manifest.schema.json"
FIXTURES = Path(__file__).parent / "fixtures" / "manifests"
VALID_YAML = FIXTURES / "valid_manifest.yaml"
VALID_JSONL = FIXTURES / "valid_manifest.jsonl"
ASSET = FIXTURES / "assets" / "points.geojson"

Doc = dict[str, Any]


@pytest.fixture
def valid_doc() -> Doc:
    return load_yaml(VALID_YAML)


def _write_yaml(directory: Path, doc: Doc, name: str = "manifest.yaml") -> Path:
    path = directory / name
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return path


def _fields(doc: Doc) -> dict[str, str]:
    return {i.field: i.message for i in validate_manifest_document(doc)}


# --- schema file ---------------------------------------------------------------------------


def test_schema_is_draft_2020_12_with_version() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["schema_version"] == "1.0.0" == MANIFEST_SCHEMA_VERSION
    Draft202012Validator.check_schema(schema)


def test_schema_requires_story_fields() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    asset = schema["$defs"]["asset"]
    expected = {
        "asset_id", "access_date", "license", "attribution", "redistributable", "sha256", "crs",
        "bbox", "time_range", "processing_steps", "split", "known_limitations",
    }  # fmt: skip
    assert expected <= set(asset["required"])
    assert asset["allOf"][0]["anyOf"] == [
        {"required": ["source_url"]},
        {"required": ["citation"]},
    ]
    assert asset["properties"]["redistributable"]["type"] == "boolean"


def test_model_and_schema_have_same_fields() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert set(DatasetManifest.model_fields) == set(schema["properties"])
    assert set(Asset.model_fields) == set(schema["$defs"]["asset"]["properties"])
    required = {name for name, f in Asset.model_fields.items() if f.is_required()}
    assert required == set(schema["$defs"]["asset"]["required"])


# --- validation behavior ---------------------------------------------------------------------


@pytest.mark.parametrize("path", [VALID_YAML, VALID_JSONL])
def test_valid_manifest(path: Path) -> None:
    assert validate_manifest_file(path) == []
    manifest = load_dataset_manifest(path)
    assert manifest.dataset_id == "example_points"
    assert manifest.assets[0].access_date == "2026-10-09"  # unquoted YAML date stays a string
    assert manifest.assets[0].redistributable is True


def test_yaml_and_jsonl_fixtures_agree() -> None:
    assert load_dataset_manifest(VALID_YAML) == load_dataset_manifest(VALID_JSONL)


def test_fixture_checksum_matches_asset() -> None:
    assert sha256_file(ASSET) == load_yaml(VALID_YAML)["assets"][0]["sha256"]


def test_missing_required_asset_field(valid_doc: Doc) -> None:
    del valid_doc["assets"][0]["license"]
    assert _fields(valid_doc) == {"assets[0]": "'license' is a required property"}


def test_source_url_or_citation_required(valid_doc: Doc) -> None:
    del valid_doc["assets"][0]["citation"]
    assert _fields(valid_doc) == {
        "assets[0]": "asset needs at least one of 'source_url' or 'citation'"
    }
    valid_doc["assets"][0]["source_url"] = "https://example.com/points.geojson"
    assert _fields(valid_doc) == {}


def test_invalid_sha256(valid_doc: Doc) -> None:
    valid_doc["assets"][0]["sha256"] = "ABC"
    assert _fields(valid_doc) == {
        "assets[0].sha256": "'ABC' is not a valid lowercase hex SHA-256 digest (64 characters)"
    }


def test_duplicate_asset_id(valid_doc: Doc) -> None:
    valid_doc["assets"].append(copy.deepcopy(valid_doc["assets"][0]))
    assert _fields(valid_doc) == {
        "assets[1].asset_id": "duplicate asset_id 'points' (first used by assets[0])"
    }


def test_jsonl_reports_bad_line(tmp_path: Path) -> None:
    path = tmp_path / "manifest.jsonl"
    path.write_text('{"schema_version": "1.0.0", "dataset_id": "x"}\n{not json\n', "utf-8")
    issues = validate_manifest_file(path)
    assert [i.field for i in issues] == ["line 2"]
    assert issues[0].message.startswith("invalid JSON")


def test_jsonl_header_must_not_hold_assets(tmp_path: Path) -> None:
    path = tmp_path / "manifest.jsonl"
    path.write_text('{"schema_version": "1.0.0", "dataset_id": "x", "assets": []}\n', "utf-8")
    assert [str(i) for i in validate_manifest_file(path)] == [
        "line 1: header line must not contain 'assets'"
    ]


def test_detect_document_type() -> None:
    assert detect_document_type(VALID_YAML) == "dataset manifest"
    assert detect_document_type(VALID_JSONL) == "dataset manifest"
    benchmark = Path(__file__).parent / "fixtures" / "benchmarks" / "valid_benchmark.yaml"
    assert detect_document_type(benchmark) == "benchmark spec"


# --- restricted assets and git ---------------------------------------------------------------


@pytest.fixture
def git_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fresh git repo that ignores data/raw/, isolated from the user's git config."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / ".gitignore").write_text("data/raw/\n", encoding="utf-8")
    return repo


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _restricted_manifest(repo: Path, valid_doc: Doc, asset_path: str) -> Path:
    """Write ``repo/datasets/manifest.yaml`` with one restricted asset at ``asset_path``."""
    target = repo / "datasets" / asset_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(ASSET.read_bytes())
    valid_doc["assets"][0].update(path=asset_path, redistributable=False, license="ODbL-1.0")
    return _write_yaml(repo / "datasets", valid_doc)


def test_restricted_asset_committed_in_tree_fails(git_repo: Path, valid_doc: Doc) -> None:
    manifest = _restricted_manifest(git_repo, valid_doc, "extract.geojson")
    _git(git_repo, "add", "datasets/extract.geojson")
    _git(git_repo, "commit", "-q", "-m", "add restricted data")
    issues = validate_manifest_file(manifest)
    assert [i.field for i in issues] == ["assets[0].path"]
    assert issues[0].message == (
        "asset 'points' has redistributable: false but its path 'extract.geojson' is tracked "
        "in git; restricted data must be referenced, not committed (untrack it with "
        "`git rm --cached` and keep it in a gitignored path such as data/raw/)"
    )


def test_restricted_asset_untracked_but_not_ignored_fails(git_repo: Path, valid_doc: Doc) -> None:
    manifest = _restricted_manifest(git_repo, valid_doc, "extract.geojson")
    issues = validate_manifest_file(manifest)
    assert [i.field for i in issues] == ["assets[0].path"]
    assert "is inside the git working tree and not gitignored" in issues[0].message


def test_restricted_asset_force_added_despite_ignore_fails(git_repo: Path, valid_doc: Doc) -> None:
    manifest = _restricted_manifest(git_repo, valid_doc, "../data/raw/extract.geojson")
    _git(git_repo, "add", "-f", "data/raw/extract.geojson")
    issues = validate_manifest_file(manifest)
    assert "is tracked in git" in issues[0].message


def test_restricted_asset_in_gitignored_path_passes(git_repo: Path, valid_doc: Doc) -> None:
    manifest = _restricted_manifest(git_repo, valid_doc, "../data/raw/extract.geojson")
    assert validate_manifest_file(manifest) == []


def test_restricted_asset_outside_any_repo_passes(tmp_path: Path, valid_doc: Doc) -> None:
    (tmp_path / "extract.geojson").write_bytes(ASSET.read_bytes())
    valid_doc["assets"][0].update(path="extract.geojson", redistributable=False)
    manifest = _write_yaml(tmp_path, valid_doc)
    assert git_path_state(tmp_path / "extract.geojson") is GitPathState.OUTSIDE
    assert validate_manifest_file(manifest) == []


def test_redistributable_asset_committed_in_tree_passes(git_repo: Path, valid_doc: Doc) -> None:
    manifest = _restricted_manifest(git_repo, valid_doc, "extract.geojson")
    doc = load_yaml(manifest)
    doc["assets"][0]["redistributable"] = True
    _write_yaml(manifest.parent, doc)
    _git(git_repo, "add", "datasets/extract.geojson")
    assert validate_manifest_file(manifest) == []


# --- checksum verification -------------------------------------------------------------------


def _copy_fixture(tmp_path: Path, valid_doc: Doc) -> Path:
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "points.geojson").write_bytes(ASSET.read_bytes())
    return _write_yaml(tmp_path, valid_doc)


def test_verify_ok() -> None:
    [check] = verify_manifest(VALID_YAML)
    assert (check.asset_id, check.status) == ("points", "ok")
    assert check.actual == check.expected


def test_verify_checksum_mismatch(tmp_path: Path, valid_doc: Doc) -> None:
    manifest = _copy_fixture(tmp_path, valid_doc)
    (tmp_path / "assets" / "points.geojson").write_text("tampered", encoding="utf-8")
    [check] = verify_manifest(manifest)
    assert check.status == "checksum_mismatch"
    assert check.actual == sha256_file(tmp_path / "assets" / "points.geojson")
    assert check.actual != check.expected


def test_verify_missing_file(tmp_path: Path, valid_doc: Doc) -> None:
    manifest = _write_yaml(tmp_path, valid_doc)
    [check] = verify_manifest(manifest)
    assert check.status == "missing"
    assert check.actual is None


def test_verify_rejects_invalid_manifest(tmp_path: Path, valid_doc: Doc) -> None:
    del valid_doc["assets"][0]["sha256"]
    with pytest.raises(SpecValidationError):
        verify_manifest(_write_yaml(tmp_path, valid_doc))


# --- CLI -------------------------------------------------------------------------------------


@pytest.mark.parametrize("path", [VALID_YAML, VALID_JSONL])
def test_cli_validate_manifest(path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["validate", str(path)]) == 0
    assert f"{path}: valid dataset manifest" in capsys.readouterr().out


def test_cli_validate_invalid_jsonl_manifest(
    tmp_path: Path, valid_doc: Doc, capsys: pytest.CaptureFixture[str]
) -> None:
    valid_doc["assets"][0]["bbox"] = [0, 0, 1]
    assets = valid_doc.pop("assets")
    path = tmp_path / "manifest.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in [valid_doc, *assets]) + "\n", "utf-8")
    assert main(["validate", str(path)]) == 1
    assert f"{path}: assets[0].bbox: [0, 0, 1] is too short" in capsys.readouterr().err


def test_cli_validate_restricted_asset_in_tree(
    git_repo: Path, valid_doc: Doc, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = _restricted_manifest(git_repo, valid_doc, "extract.geojson")
    _git(git_repo, "add", "datasets/extract.geojson")
    assert main(["validate", str(manifest)]) == 1
    err = capsys.readouterr().err
    assert f"{manifest}: assets[0].path: asset 'points' has redistributable: false" in err


def test_cli_data_verify(
    tmp_path: Path, valid_doc: Doc, capsys: pytest.CaptureFixture[str]
) -> None:
    valid_doc["assets"].append({**valid_doc["assets"][0], "asset_id": "gone", "path": "gone.json"})
    valid_doc["assets"].append({**valid_doc["assets"][0], "asset_id": "bad", "sha256": "0" * 64})
    manifest = _copy_fixture(tmp_path, valid_doc)
    assert main(["data", "verify", str(manifest)]) == 1
    out, err = capsys.readouterr()
    lines = out.splitlines()
    assert lines[0].startswith("points: ok")
    assert lines[1].startswith("gone: missing")
    assert lines[2].startswith("bad: checksum_mismatch")
    assert f"expected {'0' * 64}, got {sha256_file(ASSET)}" in lines[2]
    assert "2 of 3 asset(s) failed verification" in err


def test_cli_data_verify_all_ok(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["data", "verify", str(VALID_YAML)]) == 0
    assert capsys.readouterr().out.startswith("points: ok")


# --- Pydantic model and JSON Schema agree ----------------------------------------------------


def _set(*path: str | int, value: Any) -> Callable[[Doc], None]:
    def mutate(doc: Doc) -> None:
        target: Any = doc
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value

    return mutate


def _delete(*path: str | int) -> Callable[[Doc], None]:
    def mutate(doc: Doc) -> None:
        target: Any = doc
        for key in path[:-1]:
            target = target[key]
        del target[path[-1]]

    return mutate


def _swap_citation_for_url(doc: Doc) -> None:
    del doc["assets"][0]["citation"]
    doc["assets"][0]["source_url"] = "https://example.com/a.geojson"


AGREEMENT_CASES: dict[str, Callable[[Doc], None]] = {
    # documents both must accept
    "valid": lambda d: None,
    "source_url_only": _swap_citation_for_url,
    "source_url_and_citation": _set("assets", 0, "source_url", value="s3://bucket/a.tif"),
    "no_description": _delete("description"),
    "integer_bbox": _set("assets", 0, "bbox", value=[0, 0, 1, 1]),
    "processing_steps": _set("assets", 0, "processing_steps", value=["clip to bbox"]),
    "restricted": _set("assets", 0, "redistributable", value=False),
    # documents both must reject
    "missing_schema_version": _delete("schema_version"),
    "wrong_schema_version": _set("schema_version", value="2.0.0"),
    "bad_dataset_id": _set("dataset_id", value="Bad-ID"),
    "assets_empty": _set("assets", value=[]),
    "extra_field": _set("unexpected", value=1),
    "asset_extra_field": _set("assets", 0, "unexpected", value=1),
    "no_source": _delete("assets", 0, "citation"),
    "bad_source_url": _set("assets", 0, "source_url", value="example.com/a"),
    "missing_path": _delete("assets", 0, "path"),
    "bad_access_date": _set("assets", 0, "access_date", value="Oct 9 2026"),
    "empty_license": _set("assets", 0, "license", value=""),
    "missing_attribution": _delete("assets", 0, "attribution"),
    "redistributable_string": _set("assets", 0, "redistributable", value="false"),
    "redistributable_int": _set("assets", 0, "redistributable", value=0),
    "uppercase_sha256": _set("assets", 0, "sha256", value="A" * 64),
    "short_sha256": _set("assets", 0, "sha256", value="a" * 63),
    "missing_crs": _delete("assets", 0, "crs"),
    "bbox_three": _set("assets", 0, "bbox", value=[0, 0, 1]),
    "bbox_five": _set("assets", 0, "bbox", value=[0, 0, 1, 1, 2]),
    "bbox_string": _set("assets", 0, "bbox", value=["0", "0", "1", "1"]),
    "bbox_bool": _set("assets", 0, "bbox", value=[True, 0, 1, 1]),
    "time_range_missing_end": _delete("assets", 0, "time_range", "end"),
    "time_range_bad_date": _set("assets", 0, "time_range", "start", value="2026"),
    "processing_steps_string": _set("assets", 0, "processing_steps", value="none"),
    "bad_split": _set("assets", 0, "split", value="Test"),
    "limitations_empty": _set("assets", 0, "known_limitations", value=[]),
    "not_a_mapping": lambda d: d.clear(),
}

EXPECTED_VALID = {
    "valid",
    "source_url_only",
    "source_url_and_citation",
    "no_description",
    "integer_bbox",
    "processing_steps",
    "restricted",
}


@pytest.mark.parametrize("name", list(AGREEMENT_CASES))
def test_model_and_schema_agree(valid_doc: Doc, name: str) -> None:
    doc = copy.deepcopy(valid_doc)
    AGREEMENT_CASES[name](doc)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    schema_ok = Draft202012Validator(schema).is_valid(doc)
    try:
        DatasetManifest.model_validate(doc)
        model_ok = True
    except ValidationError:
        model_ok = False
    assert schema_ok == model_ok, f"schema accepts={schema_ok}, model accepts={model_ok}"
    assert schema_ok == (name in EXPECTED_VALID)
