"""The three modes: what each one's creator and judge are shown, and how its run ends.

    ../contextual-asr/venv/bin/python -m pytest tests -q
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config  # noqa: E402
from core.pipeline import StageError  # noqa: E402
from modules import modes  # noqa: E402
from modules.generator import BTGenerator  # noqa: E402
from modules.judge import SemanticJudge  # noqa: E402
from modules.loop_stage import loop_summary  # noqa: E402
from modules.scene import load_scene  # noqa: E402

IDS = ['static_creator', 'static_creator_dynamic_judge', 'dynamic_creator']
PHYSICAL_FACTS = (config.SHARED_PROMPTS_DIR / 'physical_facts.txt').read_text()


@pytest.fixture(scope='module')
def scene():
    return load_scene('scene8')


def creator_prompt(mode_id, scene):
    return BTGenerator(modes.get(mode_id)).system_prompt(scene)


def facts():
    """Each physical fact as one sentence, its line breaks joined."""
    text = ' '.join(PHYSICAL_FACTS.split())
    return [fact.strip() for fact in text.split('- ')[1:]]


# --- the modes themselves ------------------------------------------------------

def test_the_three_modes_in_order():
    assert list(modes.MODES) == IDS
    assert [modes.get(i).title for i in IDS] == [
        'Static creator', 'Static creator & Dynamic judge', 'Dynamic creator']
    assert [modes.get(i).uses_judge for i in IDS] == [False, True, False]
    assert [modes.get(i).creator_sees_scene for i in IDS] == [False, False, True]
    for mode_id in IDS:
        mode = modes.get(mode_id)
        assert mode.folder == config.MODES_DIR / mode_id
        assert mode.creator_prompt.exists()
        assert mode.judge_prompt is None or mode.judge_prompt.exists()
    assert config.DEFAULT_MODE in modes.MODES


@pytest.mark.parametrize('mode_id', ['judge', 'Static creator', None, ''])
def test_an_unknown_mode_is_an_error_naming_the_three(mode_id):
    with pytest.raises(StageError) as error:
        modes.get(mode_id)
    for known in IDS:
        assert known in str(error.value)


# --- what each creator and judge sees ------------------------------------------

def test_the_static_creator_sees_neither_the_scene_nor_the_physical_facts(scene):
    prompt = creator_prompt('static_creator', scene)
    flat = ' '.join(prompt.split())
    for object_id in scene.ids:
        assert object_id not in prompt, object_id
    for fact in facts():
        assert fact not in flat, fact
    assert 'Physical facts' not in prompt


def test_the_judged_creator_is_the_static_creator_and_the_judge_sees_it_all(scene):
    assert creator_prompt('static_creator_dynamic_judge', scene) == \
        creator_prompt('static_creator', scene)
    judge = SemanticJudge(modes.get('static_creator_dynamic_judge')).system_prompt(scene)
    for object_id in scene.ids:
        assert object_id in judge, object_id
    assert PHYSICAL_FACTS.rstrip('\n') in judge


def test_the_dynamic_creator_sees_the_scene_and_the_physical_facts(scene):
    prompt = creator_prompt('dynamic_creator', scene)
    assert scene.objects_block() in prompt
    for object_id in scene.ids:
        assert object_id in prompt, object_id
    for line in PHYSICAL_FACTS.splitlines():
        assert line in prompt, line
    assert 'reviewer' not in prompt.lower()
    assert '{scene_objects}' not in prompt


@pytest.mark.parametrize('mode_id', ['static_creator', 'dynamic_creator'])
def test_a_mode_without_a_judge_cannot_make_one(mode_id):
    with pytest.raises(ValueError):
        SemanticJudge(modes.get(mode_id))


def test_the_prompt_files_are_recorded(scene):
    generator = BTGenerator(modes.get('dynamic_creator')).describe()
    assert generator['prompt'] == 'modes/dynamic_creator/creator_prompt.txt'
    judge = SemanticJudge(modes.get('static_creator_dynamic_judge')).describe()
    assert judge['prompt'] == 'modes/static_creator_dynamic_judge/judge_prompt.txt'


# --- the placeholder must agree with the mode -----------------------------------

def mode_with_prompt(tmp_path, text, sees_scene):
    path = tmp_path / 'creator_prompt.txt'
    path.write_text(text)
    return modes.Mode(id='test', title='Test', folder=tmp_path, creator_prompt=path,
                      judge_prompt=None, creator_sees_scene=sees_scene)


def test_a_static_creator_prompt_with_the_scene_is_refused(tmp_path, scene):
    mode = mode_with_prompt(tmp_path, 'Scene\n{scene_objects}\n', sees_scene=False)
    with pytest.raises(StageError, match='does not show the creator the scene'):
        BTGenerator(mode).system_prompt(scene)


def test_a_dynamic_creator_prompt_without_the_scene_is_refused(tmp_path, scene):
    mode = mode_with_prompt(tmp_path, 'No scene here.\n', sees_scene=True)
    with pytest.raises(StageError, match='has no {scene_objects} placeholder'):
        BTGenerator(mode).system_prompt(scene)


def test_a_prompt_that_agrees_with_its_mode_is_filled(tmp_path, scene):
    mode = mode_with_prompt(tmp_path, 'Scene\n{scene_objects}\n', sees_scene=True)
    assert scene.objects_block() in BTGenerator(mode).system_prompt(scene)


# --- the summary -----------------------------------------------------------------

def test_the_summary_records_the_mode():
    record = {'status': 'no_judge', 'counts': {}, 'attempts': [],
              'times': {'first_valid_tree': None, 'accepted': None}}
    payload = {'mode': 'dynamic_creator', 'mode_title': 'Dynamic creator',
               'generator': {'model': 'gpt-4o'}, 'judge': None}
    summary = loop_summary(record, payload)
    assert summary['mode'] == {'id': 'dynamic_creator', 'title': 'Dynamic creator'}
    assert summary['models'] == {'generator': {'model': 'gpt-4o'}, 'judge': None}
    assert 'judge_enabled' not in summary and 'enrichment' not in summary
