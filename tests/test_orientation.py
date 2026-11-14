import numpy as np

from smartscan.orientation import OrientationVote, should_auto_rotate, vote


def test_no_evidence_returns_unknown():
    blank = np.full((64, 64, 3), 180, dtype=np.uint8)
    result = vote(blank)
    assert result.state == "unknown"
    assert should_auto_rotate(result) == 0


def test_single_weak_signal_does_not_auto_rotate():
    v = OrientationVote(state="unknown", signals={"horizon": 90}, confidence=0.4)
    assert should_auto_rotate(v) == 0


def test_two_agreeing_strong_signals_auto_rotate():
    v = OrientationVote(state="voted", signals={"horizon": 90, "lines": 90}, confidence=0.9)
    assert should_auto_rotate(v) == 90


def test_180_degree_evidence_never_auto_rotates():
    v = OrientationVote(
        state="voted", signals={"sky_ground": 180, "lines": 180}, confidence=0.95
    )
    assert should_auto_rotate(v) == 0
