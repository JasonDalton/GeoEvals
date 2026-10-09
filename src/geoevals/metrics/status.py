"""Task status metric: does the predicted ``status`` equal the reference ``status``?"""

from collections.abc import Mapping
from typing import Any

from geoevals.metrics.base import Metric, MetricValue

ANSWER_STATUS = "ok"
ABSTAIN_STATUSES = frozenset({"needs_clarification", "insufficient_data", "invalid_request"})
"""The statuses that decline to answer: ask for clarification or refuse."""


def _status(document: Any) -> Any:
    return document.get("status") if isinstance(document, Mapping) else None


def _mismatch_reason(predicted: Any, expected: Any) -> str:
    if expected in ABSTAIN_STATUSES and predicted == ANSWER_STATUS:
        return "answered_when_should_abstain"
    if expected == ANSWER_STATUS and predicted in ABSTAIN_STATUSES:
        return "abstained_when_should_answer"
    if expected in ABSTAIN_STATUSES and predicted in ABSTAIN_STATUSES:
        return "wrong_abstention_status"
    return "status_differs"


class StatusMatch(Metric):
    """1.0 when the prediction's ``status`` equals the reference's ``status``, else 0.0.

    Compares the two strings exactly (no units, no tolerance). A prediction or reference that is
    not a mapping, or has no ``status``, counts as status null; null equals only null.
    ``detail`` always holds ``predicted`` and ``expected``; a mismatch adds a ``reason``:
    ``answered_when_should_abstain`` (``ok`` for an abstention reference),
    ``abstained_when_should_answer``, ``wrong_abstention_status`` or ``status_differs``.
    """

    id = "status_match"
    version = "1.1.0"
    units = "fraction"
    higher_is_better = True

    def score(self, prediction: Any, reference: Any, params: Mapping[str, Any]) -> MetricValue:
        predicted, expected = _status(prediction), _status(reference)
        detail: dict[str, Any] = {"predicted": predicted, "expected": expected}
        if predicted == expected:
            return MetricValue(value=1.0, passed=True, detail=detail)
        detail["reason"] = _mismatch_reason(predicted, expected)
        return MetricValue(value=0.0, passed=False, detail=detail)
