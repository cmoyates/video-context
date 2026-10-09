"""Small, checked readers for external JSON values."""

import math


def object_(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError("Expected a JSON object")
    return dict(value)


def objects(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise ValueError("Expected a JSON array")
    return [object_(item) for item in value]


def text(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Expected text")
    return value


def integer(value: object) -> int:
    if type(value) is not int:
        raise ValueError("Expected an integer")
    return value


def number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Expected a finite number")
    return float(value)


def boolean(value: object) -> bool:
    if type(value) is not bool:
        raise ValueError("Expected a boolean")
    return value
