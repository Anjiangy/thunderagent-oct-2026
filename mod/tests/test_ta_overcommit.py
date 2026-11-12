import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))
import ta_overcommit_watch as w  # noqa: E402

def mk(cap=1000, intended=0, reported=0, running=0, paused=0):
    return w.Sample(ts=0.0, capacity=cap, intended=intended, reported=reported,
                    running=running, paused=paused)


def test_empty_is_ok():
    assert w.classify(mk(intended=0, reported=0)) == w.OK


def test_blind_when_running_but_zero_usage():
    assert w.classify(mk(intended=100, reported=0, running=1)) == w.BLIND


def test_blind_by_coverage():
    assert w.classify(mk(intended=700, reported=50, running=0)) == w.BLIND


def test_ok_when_low_fill_and_low_coverage():
    # 30% full, zero coverage: not close enough to the wall to warn
    assert w.classify(mk(intended=300, reported=0, running=0)) == w.OK


def test_tight_when_full_and_unpaused():
    assert w.classify(mk(intended=950, reported=900, running=5, paused=0)) == w.TIGHT


def test_tight_needs_no_pause():
    assert w.classify(mk(intended=950, reported=900, running=5, paused=2)) == w.OK


def test_window_hysteresis():
    assert w.decide([w.BLIND], 3) == w.OK
    assert w.decide([w.BLIND, w.BLIND, w.BLIND], 3) == w.BLIND
    assert w.decide([w.BLIND, w.BLIND, w.OK], 3) == w.OK


def test_coverage_and_fill_math():
    s = mk(intended=500, reported=250)
    assert abs(s.coverage - 0.5) < 1e-9
    assert abs(s.fill - 0.5) < 1e-9