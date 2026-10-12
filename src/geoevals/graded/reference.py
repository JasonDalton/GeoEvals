"""Load an eval's reference script (``reference`` in ``eval.yaml``).

The script defines ``compute_key(key_type, params, layers) -> dict``. It is loaded from its
file, as a benchmark's ``reference.py`` is (``geoevals.regenerate``), so that it lives with the
evals it serves instead of in the package.
"""

import importlib.util
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, cast

import geopandas as gpd

from geoevals.graded.spec import spec_file
from geoevals.validation import EvalSpec

ComputeKey = Callable[[str, Mapping[str, Any], Mapping[str, gpd.GeoDataFrame]], dict[str, Any]]


class ReferenceLoadError(RuntimeError):
    """The reference script cannot be loaded or has no ``compute_key``."""


def load_reference(spec_path: Path, spec: EvalSpec) -> ComputeKey:
    path = spec_file(spec_path, spec.reference)
    if not path.is_file():
        raise ReferenceLoadError(f"{path}: reference script not found")
    module_spec = importlib.util.spec_from_file_location(f"geoevals_eval_reference_{spec.id}", path)
    if module_spec is None or module_spec.loader is None:
        raise ReferenceLoadError(f"{path}: cannot be loaded as a Python module")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    compute = getattr(module, "compute_key", None)
    if not callable(compute):
        raise ReferenceLoadError(f"{path}: defines no compute_key(key_type, params, layers)")
    return cast(ComputeKey, compute)
