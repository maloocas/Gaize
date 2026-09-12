"""Guards the spoken announcement on a gesture click.

A wink click is otherwise silent, which leaves a user who is not reading the
screen with no idea what was just pressed. Source-level checks, like the rest
of the controller tests: controller.py needs AppKit and a camera.
"""
from pathlib import Path

SOURCE = (Path(__file__).parents[1] / "native" / "controller.py").read_text()


def _body(name: str) -> str:
    start = SOURCE.index(f"def {name}")
    rest = SOURCE[start:]
    cut = rest.find("\n    def ", 1)
    return rest[:cut] if cut != -1 else rest


def test_a_wink_click_announces_the_target():
    body = _body("handle_gesture")
    assert "speak(click_phrase(" in body
    # Said while the selection is still known - clear_selection() drops it.
    assert body.index("speak(click_phrase(") < body.index("self.clear_selection()")


def test_the_phrase_names_the_target_and_falls_back_to_a_generic_one():
    body = _body("click_phrase")
    assert '"Pressing {name}."' in body or "f\"Pressing {name}.\"" in body
    assert "Pressing this." in body


def test_the_phrase_avoids_words_that_come_back_as_voice_commands():
    # The companion app listens for "click"/"select" as a select command, so
    # saying either aloud re-triggers it through the mic in a loop.
    body = _body("click_phrase").lower()
    assert "clicking" not in body.split('"""')[-1]
    assert "selecting" not in body


def test_speech_never_blocks_the_pointer_loop():
    body = _body("speak")
    # Popen, not run/call: `say` blocks for the length of the utterance.
    assert "subprocess.Popen" in body
    assert "subprocess.run(\"say\"" not in body
    # A new utterance cuts off the previous one rather than queueing.
    assert "terminate()" in body


def test_an_uninstalled_voice_falls_back_instead_of_going_silent():
    body = _body("speak")
    assert 'say", "-v", "?"' in body
    assert "_speech_voice = SPEECH_VOICE if any(" in body
