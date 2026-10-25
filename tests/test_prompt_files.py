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
    assert '{scene_objects}' in text


def test_the_actions_and_physical_facts_are_in_the_prompts():
    generation = load_prompt(config.BT_GENERATION_PROMPT_FILE)
    judge = load_prompt(config.SEMANTIC_JUDGE_PROMPT_FILE)
    assert 'Place(name, obj, location)' in generation
    shared = (config.BT_GENERATION_PROMPT_FILE.parent / 'robot_and_workspace.txt').read_text()
    assert shared.rstrip('\n') in generation and shared.rstrip('\n') in judge
    assert 'Place(obj, location)' in judge
    assert 'Physical facts' in judge
    # The generator is not given physical rules; they belong to the judge.
    assert 'Physical facts' not in generation


def test_every_part_file_is_used():
    used = set()
    for path in MAIN_PROMPTS:
        used |= {path.parent / name for name in
                 re.findall(r'\{\{include:\s*(.+?)\s*\}\}', path.read_text())}
    parts = set(config.BT_GENERATION_PROMPT_FILE.parent.glob('*.txt')) - set(MAIN_PROMPTS)
    assert parts == used
