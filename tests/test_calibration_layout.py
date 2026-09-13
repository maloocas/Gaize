from pathlib import Path


SOURCE = (Path(__file__).parents[1] / "native" / "controller.py").read_text()


def test_keyboard_calibration_is_three_points_wide_and_tall():
    assert "KEYBOARD_CAL_XS = (.10, .50, .90)" in SOURCE
    assert "KEYBOARD_CAL_YS = (.36, .55, .74)" in SOURCE
    assert "[(x,y) for y in KEYBOARD_CAL_YS for x in KEYBOARD_CAL_XS]" in SOURCE
    assert "CAL_POINTS = SCREEN_CAL_POINTS + KEYBOARD_CAL_POINTS" in SOURCE


def test_keyboard_calibration_stays_inside_padded_letter_region():
    # These explicit bounds leave the one-key padding around the keyboard and
    # avoid spending samples on its edge-action bands.
    assert "(.10, .50, .90)" in SOURCE
    assert "(.36, .55, .74)" in SOURCE
