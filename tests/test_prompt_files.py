"""A prompt can include other files, which are put in place when it is loaded.

Run from the pipeline folder:

    ../contextual-asr/venv/bin/python -m pytest tests -q
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.pipeline import StageError  # noqa: E402
from modules.prompt_files import load_prompt  # noqa: E402


def test_include_is_replaced_by_the_file(tmp_path):
    (tmp_path / 'part.txt').write_text('Actions\n- Place\n')
    main = tmp_path / 'main.txt'
    main.write_text('Intro\n\n{{include: part.txt}}\n\nEnd\n')
    assert load_prompt(main) == 'Intro\n\nActions\n- Place\n\nEnd\n'


def test_include_path_is_relative_to_the_including_file(tmp_path):
    (tmp_path / 'sub').mkdir()
    (tmp_path / 'sub' / 'inner.txt').write_text('inner')
    (tmp_path / 'sub' / 'outer.txt').write_text('outer\n{{include: inner.txt}}')
    main = tmp_path / 'main.txt'
    main.write_text('{{include: sub/outer.txt}}')
    assert load_prompt(main) == 'outer\ninner'


def test_missing_include_is_an_error(tmp_path):
    main = tmp_path / 'main.txt'
    main.write_text('{{include: nowhere.txt}}')
    with pytest.raises(StageError):
        load_prompt(main)


def test_endless_include_is_an_error(tmp_path):
    main = tmp_path / 'main.txt'
    main.write_text('{{include: main.txt}}')
    with pytest.raises(StageError):
        load_prompt(main)
