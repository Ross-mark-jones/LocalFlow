from localflow.hotkey import TapTracker


def test_hold_to_talk():
    t = TapTracker()
    assert t.press(0.0) == "start"
    assert t.release(2.0) == "finish"


def test_single_short_tap_discards():
    t = TapTracker()
    assert t.press(0.0) == "start"
    assert t.release(0.1) == "discard"


def test_double_tap_locks_then_tap_finishes():
    t = TapTracker()
    assert t.press(0.0) == "start"
    assert t.release(0.1) == "discard"
    assert t.press(0.3) == "start"      # second tap begins the real recording
    assert t.release(0.4) == "lock"     # → hands-free
    assert t.locked
    assert t.press(5.0) == "finish"     # next tap ends it
    assert t.release(5.1) == "none"     # its release is swallowed
    assert not t.locked


def test_slow_second_tap_does_not_lock():
    t = TapTracker()
    t.press(0.0)
    assert t.release(0.1) == "discard"
    t.press(2.0)                         # too late to be a double-tap
    assert t.release(2.1) == "discard"


def test_hold_after_tap_is_normal_dictation():
    t = TapTracker()
    t.press(0.0)
    t.release(0.1)
    t.press(0.3)
    assert t.release(1.5) == "finish"    # held long → normal dictation, no lock


def test_cancel_resets_lock():
    t = TapTracker()
    t.press(0.0); t.release(0.1); t.press(0.3); t.release(0.4)
    assert t.locked
    t.cancel()
    assert not t.locked
    assert t.press(1.0) == "start"       # back to normal


def test_no_lock_after_hold_then_tap():
    t = TapTracker()
    t.press(0.0)
    assert t.release(2.0) == "finish"    # long dictation
    t.press(2.2)
    assert t.release(2.3) == "discard"   # quick tap right after must not lock
