from pathlib import Path

from native.swipe_decoder import SwipeDecoder


def layout():
    keys={}
    for y,row in enumerate(("qwertyuiop","asdfghjkl","zxcvbnm")):
        offset=(10-len(row))/2
        for x,char in enumerate(row): keys[char]=((x+offset)*100,y*100)
    return keys


def test_gaize_decoder_ranks_ideal_hello_path_first():
    root=Path(__file__).parents[1]
    decoder=SwipeDecoder(root/"native"/"swipe_words.txt")
    keys=layout(); decoder.set_layout(keys,100)
    path=[]
    for char in "hello": path.extend([keys[char]]*5)
    assert decoder.decode(path)[0]=="hello"


def test_native_keyboard_records_swipe_during_double_blink_mode():
    source=(Path(__file__).parents[1]/"native"/"controller.py").read_text()
    # The path must be recorded in panel-local coordinates (via panel_point()),
    # not raw screen coordinates: the key centres it gets matched against in
    # decode() are panel-local, and mixing the two spaces silently broke every
    # swipe decode until this was fixed - the pointer only lined up with the
    # keyboard by coincidence when the panel sat at the screen origin.
    assert "self.swipe_path.append(local)" in source
    assert "local=self.panel_point()" in source
    assert "results=self.swipe_decoder.decode(self.swipe_path)" in source
    assert "class SwipeTraceView" in source


def test_python_helpers_are_not_misread_as_objc_selectors():
    source=(Path(__file__).parents[1]/"native"/"controller.py").read_text()
    assert "def makeKey_" not in source
    assert "def finishSwipe_" not in source
    assert "def make_key" in source
    assert "def finish_swipe" in source
