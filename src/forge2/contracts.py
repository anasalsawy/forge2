"""Exact output contracts and parsers used by deterministic gates."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class FloorVerdict(StrEnum):
    PASS = "PASS"
    CORRECTION_REQUIRED = "CORRECTION_REQUIRED"
    PASS_WITH_NOTES = "PASS_WITH_NOTES"


class FinalVerdict(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"


class HumanDecision(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    RERUN = "RERUN"


@dataclass(frozen=True)
class ParsedFloorReview:
    verdict: FloorVerdict
    feedback: str


_FLOOR_LINE = re.compile(r"^VERDICT:\s*(PASS|CORRECTION_REQUIRED|PASS_WITH_NOTES)\s*$")
_FINAL_LINE = re.compile(r"^FINAL_VERDICT:\s*(PASS|FAIL)\s*$")


def _last_nonempty_line(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        raise ValueError("empty model output")
    return lines[-1]


def parse_floor_review(text: str) -> ParsedFloorReview:
    """Accept a verdict only when the final non-empty line exactly matches the contract."""
    match = _FLOOR_LINE.fullmatch(_last_nonempty_line(text))
    if not match:
        raise ValueError("review must end with exactly VERDICT: PASS, CORRECTION_REQUIRED, or PASS_WITH_NOTES")
    return ParsedFloorReview(FloorVerdict(match.group(1)), text.strip())


def parse_final_verdict(text: str) -> FinalVerdict:
    """Accept a release verdict only from the exact final line."""
    match = _FINAL_LINE.fullmatch(_last_nonempty_line(text))
    if not match:
        raise ValueError("audit must end with exactly FINAL_VERDICT: PASS or FINAL_VERDICT: FAIL")
    return FinalVerdict(match.group(1))


def parse_human_decision(value: str) -> HumanDecision:
    """Human decisions are exact values, never substring matches or model-generated guesses."""
    normalized = value.strip().upper()
    try:
        return HumanDecision(normalized)
    except ValueError as exc:
        raise ValueError("human decision must be exactly APPROVE, REJECT, or RERUN") from exc

