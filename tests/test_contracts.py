import pytest

from forge2.contracts import (
    FinalVerdict,
    FloorVerdict,
    HumanDecision,
    parse_final_verdict,
    parse_floor_review,
    parse_human_decision,
)


def test_floor_gate_requires_exact_final_line():
    assert parse_floor_review("review\nVERDICT: PASS").verdict is FloorVerdict.PASS
    with pytest.raises(ValueError):
        parse_floor_review("VERDICT: PASS\nbut actually rejected")
    with pytest.raises(ValueError):
        parse_floor_review("NOT VERDICT: PASS")


def test_final_gate_does_not_accept_negated_or_embedded_pass():
    assert parse_final_verdict("evidence\nFINAL_VERDICT: FAIL") is FinalVerdict.FAIL
    with pytest.raises(ValueError):
        parse_final_verdict("not FINAL_VERDICT: PASS")
    with pytest.raises(ValueError):
        parse_final_verdict("FINAL_VERDICT: PASS\nFINAL_VERDICT: FAIL because broken")


def test_human_decision_is_exact():
    assert parse_human_decision(" approve ") is HumanDecision.APPROVE
    with pytest.raises(ValueError):
        parse_human_decision("I APPROVE this")

