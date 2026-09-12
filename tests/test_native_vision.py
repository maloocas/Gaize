from pathlib import Path


def test_controller_uses_compatible_vision_options():
    source = (Path(__file__).parents[1] / "native" / "controller.py").read_text()
    assert "initWithData_options_(data,None)" in source
    assert "initWithData_options_(data,{})" not in source
