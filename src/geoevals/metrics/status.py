"""Task status metric: does the predicted ``status`` equal the reference ``status``?"""

from collections.abc import Mapping
from typing import Any

from geoevals.metrics.base import Metric, MetricValue


def _status(document: Any) -> Any:
    return document.get("status") if isinstance(document, Mapping) else None


class StatusMatch(Metric):
    """1.0 when the prediction's ``status`` equals the reference's ``status``, else 0.0.

    Compares the two strings exactly (no units, no tolerance). A prediction or reference that is
    not a mapping, or has no ``status``, counts as status null; null equals only null.
    """

    id = "status_match"
    version = "1.0.0"
    units = "fraction"
    higher_is_better = True

    def score(self, prediction: Any, reference: Any, params: Mapping[str, Any]) -> MetricValue:
        predicted, expected = _status(prediction), _status(reference)
        if predicted == expected:
            return MetricValue(value=1.0, passed=True)
        return MetricValue(
            value=0.0, passed=False, detail={"predicted": predicted, "expected": expected}
        )
