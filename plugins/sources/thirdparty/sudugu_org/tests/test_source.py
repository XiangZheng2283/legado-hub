import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parents[1]))

from source import Source


def test_chapter_stem_accepts_hyphen_and_underscore_pagination():
    source = Source()

    assert source._chapter_stem("/65/28357.html") == "/65/28357"
    assert source._chapter_stem("/65/28357-2.html") == "/65/28357"
    assert source._chapter_stem("/65/28357_3.html") == "/65/28357"
