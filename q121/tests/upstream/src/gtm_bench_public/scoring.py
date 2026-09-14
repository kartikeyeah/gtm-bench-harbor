from __future__ import annotations

from typing import Any


RAW_SCORE_FIELDS = (
    "identity_resolution_score",
    "claim_support_score",
    "database_consistency_score",
    "contact_usability_score",
)


def normalize_dimension_score(score: int | float) -> float:
    bounded = max(1.0, min(5.0, float(score)))
    return round((bounded - 1.0) / 4.0, 6)


def normalize_audit_scores(result: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(result)
    normalized_values: list[float] = []
    for field in RAW_SCORE_FIELDS:
        raw_score = _raw_score(normalized.get(field))
        normalized[field] = raw_score
        normalized[f"{field.removesuffix('_score')}_normalized"] = normalize_dimension_score(raw_score)
        normalized_values.append(normalize_dimension_score(raw_score))

    total = sum(normalized_values) / len(normalized_values)
    normalized["total_score"] = round(max(0.0, min(1.0, total)), 6)
    normalized["unsupported_claims"] = _list_or_empty(normalized.get("unsupported_claims"))
    normalized["contradicted_claims"] = _list_or_empty(normalized.get("contradicted_claims"))
    return normalized


def _raw_score(value: Any) -> int:
    try:
        return max(1, min(5, round(float(value))))
    except (TypeError, ValueError):
        return 1


def _list_or_empty(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]
