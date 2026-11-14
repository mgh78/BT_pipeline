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

MODES = config.PIPELINE_ROOT / 'modes'
SHARED = config.PIPELINE_ROOT / 'prompts' / 'shared'
STATIC_CREATOR = MODES / 'static_creator' / 'creator_prompt.txt'
JUDGED_CREATOR = MODES / 'static_creator_dynamic_judge' / 'creator_prompt.txt'
DYNAMIC_CREATOR = MODES / 'dynamic_creator' / 'creator_prompt.txt'
MAIN_PROMPTS = [STATIC_CREATOR, JUDGED_CREATOR, DYNAMIC_CREATOR,
                config.SEMANTIC_JUDGE_PROMPT_FILE]


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
    # Only the judge and the Dynamic creator are shown the scene.
    shown = path in (config.SEMANTIC_JUDGE_PROMPT_FILE, DYNAMIC_CREATOR)
    assert ('{scene_objects}' in text) == shown


def test_both_static_creator_prompts_are_the_same_prompt():
    assert load_prompt(JUDGED_CREATOR) == load_prompt(STATIC_CREATOR)
    assert JUDGED_CREATOR.read_text().strip() == (
        '{{include: ../static_creator/creator_prompt.txt}}')


def test_both_prompts_include_the_shared_parts():
    folder = SHARED
    generation = load_prompt(config.BT_GENERATION_PROMPT_FILE)
    judge = load_prompt(config.SEMANTIC_JUDGE_PROMPT_FILE)
    robot = (folder / 'robot_and_workspace.txt').read_text().rstrip('\n')
    assert robot in generation and robot in judge
    # Both read the generic actions, with {key} references.
    actions = (folder / 'generic_actions.txt').read_text().rstrip('\n')
    assert actions in generation and actions in judge
    perception = (folder / 'perception.txt').read_text().rstrip('\n')
    assert perception in generation and perception in judge
    assert (folder / 'physical_facts.txt').read_text().rstrip('\n') in judge


def test_the_generation_prompt_has_no_physical_facts():
    generation = load_prompt(config.BT_GENERATION_PROMPT_FILE)
    assert 'Place(name, obj, location)' in generation
    # The generator is not given physical rules; they belong to the judge.
    assert 'Physical facts' not in generation


def test_the_perception_vocabulary_in_the_config_is_in_the_prompt_file():
    text = (SHARED / 'perception.txt').read_text()
    flat = ' '.join(text.split())
    for value in config.PERCEPTION_TYPES:
        assert value in flat, value
    for name in (*config.PERCEPTION_COLOR_PROPERTIES, *config.PERCEPTION_BOOLEAN_PROPERTIES):
        assert f'- {name}:' in text, name


def test_the_generation_prompt_asks_for_xml_and_every_decorator_of_the_config():
    generation = load_prompt(config.BT_GENERATION_PROMPT_FILE)
    assert '```xml' in generation and 'create_behavior_tree' not in generation
    assert '@' not in generation          # references are written {key} now
    for decorator in config.GRAMMAR_DECORATORS:
        assert f'- {decorator}(name' in generation, decorator


def test_the_has_count_comparisons_in_the_config_are_in_the_generation_prompt():
    prompt = ' '.join(config.BT_GENERATION_PROMPT_FILE.read_text().split())
    for comparison in config.HAS_COUNT_COMPARISONS:
        assert f'"{comparison}"' in prompt, comparison
