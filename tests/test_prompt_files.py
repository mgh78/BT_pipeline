"""A prompt can include other files, which are put in place when it is loaded.

Run from the pipeline folder:

    ../contextual-asr/venv/bin/python -m pytest tests -q
"""

import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from core.pipeline import StageError  # noqa: E402
from modules.prompt_files import INCLUDE_PATTERN, load_prompt  # noqa: E402

MAIN_PROMPTS = [config.BT_GENERATION_PROMPT_FILE, config.SEMANTIC_JUDGE_PROMPT_FILE]


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


@pytest.mark.parametrize('path', MAIN_PROMPTS, ids=lambda p: p.name)
def test_real_prompts_assemble_completely(path):
    text = load_prompt(path)
    assert not INCLUDE_PATTERN.search(text)
    if path == config.SEMANTIC_JUDGE_PROMPT_FILE:
        assert '{scene_objects}' in text      # the generic generator is not shown the scene


def test_both_prompts_include_the_shared_parts():
    folder = config.SEMANTIC_JUDGE_PROMPT_FILE.parent
    generation = load_prompt(config.BT_GENERATION_PROMPT_FILE)
    judge = load_prompt(config.SEMANTIC_JUDGE_PROMPT_FILE)
    for name in ('robot_and_workspace.txt', 'actions.txt'):
        text = (folder / name).read_text().rstrip('\n')
        assert text in generation and text in judge
    assert (folder / 'judge_physical_facts.txt').read_text().rstrip('\n') in judge


def test_the_generation_prompt_has_no_physical_facts():
    generation = load_prompt(config.BT_GENERATION_PROMPT_FILE)
    assert 'Place(name, obj, location)' in generation
    # The generator is not given physical rules; they belong to the judge.
    assert 'Physical facts' not in generation
