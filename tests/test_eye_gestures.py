from native.blink_gestures import GestureDetector
from native.snapping import candidates, pick, to_zoom, zoom_dest, zoom_region
from native.swipe_session import SwipeSession
from native import llm


def run(detector, frames, fps=30):
    """frames: [(left, right, squint)]; returns gestures emitted, with trailing open frames."""
    out = []
    for i, (left, right, squint) in enumerate(frames + [(0, 0, 0)] * 3):
        g = detector.feed(i / fps, left, right, squint)
        if g: out.append(g)
    return out


def closure(n, left=1.0, right=1.0, squint=0.0):
    return [(0, 0, 0)] * 3 + [(left, right, squint)] * n


def test_short_soft_both_eye_closure_is_a_natural_blink():
    assert run(GestureDetector(), closure(5)) == ["blink"]


def test_longer_or_squeezed_closure_is_a_hard_blink():
    assert run(GestureDetector(), closure(15)) == ["hard_blink"]
    assert run(GestureDetector(), closure(5, squint=0.9)) == ["hard_blink"]


def test_resting_eyes_is_no_gesture():
    assert run(GestureDetector(), closure(90)) == []


def test_one_eye_closures_are_winks():
    assert run(GestureDetector(), closure(8, left=0.9, right=0.1)) == ["wink_left"]
    assert run(GestureDetector(), closure(8, left=0.1, right=0.9)) == ["wink_right"]
    # The open eye half-closes too during a real wink.
    assert run(GestureDetector(), closure(8, left=0.95, right=0.6)) == ["wink_left"]
    # Only one eye crosses the threshold, with a small average gap (real log).
    assert run(GestureDetector(), closure(6, left=0.55, right=0.43)) == ["wink_left"]


def test_resting_squint_does_not_turn_every_blink_hard():
    assert run(GestureDetector(), closure(5, squint=0.65)) == ["blink"]


def test_a_flicker_is_not_a_wink_and_lost_face_cancels():
    assert run(GestureDetector(), closure(1, left=0.9, right=0.1)) == []
    d = GestureDetector()
    d.feed(0, 1, 1); assert d.feed(0.1, None, None) is None
    assert d.feed(0.2, 0, 0) is None


def test_snap_candidates_and_pick():
    a = {"x": 0, "y": 0, "width": 50, "height": 20}
    b = {"x": 100, "y": 0, "width": 50, "height": 20}
    far = {"x": 900, "y": 900, "width": 10, "height": 10}
    assert candidates([a, b, far], 60, 10, radius=90) == [a, b]
    assert pick([a, b], 120, 10) is b


def test_zoom_keeps_aspect_and_maps_targets_inside_the_screen():
    targets = [{"x": 400, "y": 300, "width": 30, "height": 20},
               {"x": 460, "y": 310, "width": 30, "height": 20}]
    region = zoom_region(targets, 1600, 1000)
    assert abs(region[2] / region[3] - 1.6) < 1e-6
    dest = zoom_dest(region, 1600, 1000)
    for t in targets:
        z = to_zoom(t, region, dest)
        assert 0 <= z["x"] and z["x"] + z["width"] <= 1600
        assert z["width"] > t["width"] * 2      # actually magnified


class FakeDecoder:
    def decode_scored(self, path, limit, radius):
        return [(1.0 + len(path) * 0.01, "hello"), (1.5, "hells")]


def test_session_merges_offsets_into_one_slot_per_word():
    s = SwipeSession(FakeDecoder())
    s.feed(0, 0, 0.0)
    s.boundary(0.0)
    for i in range(30): s.feed(i, i, i * 0.033)
    s.boundary(1.0)
    s.end()
    assert len(s.slots) == 1                  # the empty second word adds nothing
    words = [c["word"] for c in s.slots[0]]
    assert words == ["hello", "hells"]
    assert abs(sum(c["p"] for c in s.slots[0]) - 1) < 1e-9


def test_llm_prompt_parse_and_fallback(monkeypatch):
    slots = [[{"word": w} for w in ("hi", "ho", "hu", "ha", "he", "hy")], [{"word": "there"}]]
    prompt = llm.build_prompt(slots, "")
    assert "1. hi ho hu ha he\n" in prompt and "hy" not in prompt
    reply = {"output": [{"type": "message", "content": [
        {"type": "output_text", "text": "1. hi\n2. there\nSentence: Hi there."}]}]}
    assert llm.parse_reply(reply) == "Hi there."
    monkeypatch.setattr(llm, "_api_key", lambda: "")
    assert llm.decode_sentence(slots) == ("hi there", "no OPENAI_API_KEY")
