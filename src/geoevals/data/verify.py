"""Recompute SHA-256 checksums of the local assets listed in a dataset manifest."""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from geoevals.validation.validate import load_dataset_manifest

AssetStatus = Literal["ok", "missing", "checksum_mismatch"]

_CHUNK_BYTES = 1 << 20


@dataclass(frozen=True)
class AssetCheck:
    """Checksum result for one manifest asset. ``actual`` is None when the file is missing."""

    asset_id: str
    path: Path
    status: AssetStatus
    expected: str
    actual: str | None


def sha256_file(path: Path) -> str:
    """Return the lowercase hex SHA-256 digest of the file at ``path``."""
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def verify_manifest(manifest_path: Path) -> list[AssetCheck]:
    """Check every asset in the manifest; asset paths are relative to the manifest file.

    Raises ``SpecValidationError`` if the manifest fails schema validation.
    """
    manifest = load_dataset_manifest(manifest_path, check_git=False)
    checks: list[AssetCheck] = []
    for asset in manifest.assets:
        path = manifest_path.parent / asset.path
        if not path.is_file():
            checks.append(AssetCheck(asset.asset_id, path, "missing", asset.sha256, None))
            continue
        actual = sha256_file(path)
        status: AssetStatus = "ok" if actual == asset.sha256 else "checksum_mismatch"
        checks.append(AssetCheck(asset.asset_id, path, status, asset.sha256, actual))
    return checks
