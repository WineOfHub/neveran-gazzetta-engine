from __future__ import annotations

import re

_RESET_DURATION = re.compile(
    r"^(?:(?P<hours>\d+(?:\.\d+)?)h)?"
    r"(?:(?P<minutes>\d+(?:\.\d+)?)m)?"
    r"(?:(?P<seconds>\d+(?:\.\d+)?)s)?$"
)


def parse_rate_limit_reset(value: object) -> float | None:
    text = str(value or "").strip().lower()
    if not text:
        return None
    if text.endswith("ms"):
        try:
            return float(text[:-2]) / 1000
        except ValueError:
            return None
    try:
        return float(text)
    except ValueError:
        pass
    match = _RESET_DURATION.fullmatch(text)
    if match is None or not any(match.groupdict().values()):
        return None
    return (
        float(match.group("hours") or 0) * 3600
        + float(match.group("minutes") or 0) * 60
        + float(match.group("seconds") or 0)
    )
