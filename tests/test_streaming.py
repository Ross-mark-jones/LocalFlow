import numpy as np

from localflow.recorder import Recorder, SAMPLE_RATE


def _speech(seconds: float, level: float = 0.3) -> np.ndarray:
    n = int(seconds * SAMPLE_RATE)
    return (np.random.default_rng(0).standard_normal((n, 1)).astype(np.float32) * level)


def _silence(seconds: float) -> np.ndarray:
    return np.zeros((int(seconds * SAMPLE_RATE), 1), dtype=np.float32)


def _load(rec: Recorder, chunk: np.ndarray) -> None:
    """Inject audio as if the mic delivered it, without opening a real stream."""
    rec._capturing = True
    rec._chunks.append(chunk)


def test_no_flush_before_min_speech():
    r = Recorder()
    _load(r, _speech(0.5))
    assert r.flush_segment(min_speech_seconds=1.0) is None  # too short


def test_no_flush_while_still_speaking():
    r = Recorder()
    _load(r, _speech(2.0))  # 2s speech, no trailing pause
    assert r.flush_segment(pause_seconds=0.7, max_segment_seconds=30) is None


def test_flush_on_pause():
    r = Recorder()
    _load(r, _speech(2.0))
    _load(r, _silence(0.8))  # trailing pause → flush
    seg = r.flush_segment(pause_seconds=0.7, min_speech_seconds=1.0)
    assert seg is not None
    assert len(r._chunks) == 0  # buffer cleared for the next segment


def test_flush_on_max_segment_even_without_pause():
    r = Recorder()
    _load(r, _speech(31.0))  # never pauses → force flush at max
    seg = r.flush_segment(max_segment_seconds=30)
    assert seg is not None


def test_pure_silence_is_dropped_not_emitted():
    r = Recorder()
    _load(r, _silence(2.0))
    assert r.flush_segment(min_speech_seconds=1.0) is None
    _load(r, _silence(1.0))
    assert r.flush_segment(min_speech_seconds=1.0) is None


def test_second_segment_after_flush():
    r = Recorder()
    _load(r, _speech(1.5))
    _load(r, _silence(0.8))
    assert r.flush_segment() is not None
    # new speech arrives — next flush returns it, independent of the first
    _load(r, _speech(1.5))
    _load(r, _silence(0.8))
    assert r.flush_segment() is not None
