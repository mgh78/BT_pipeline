"""The ten loop cases, run against the real pipeline.

The model is replaced with scripted replies; everything else is real - the scene, the
syntax check, the judgement form and the caps. Each case asserts the status a run ends
with, how many calls it took, and what the next message actually carried back to the
generator.

    ../contextual-asr/venv/bin/python -m pytest tests -q
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from core.pipeline import Pipeline  # noqa: E402
from core.run_context import RunContext  # noqa: E402
from modules import llm  # noqa: E402
from modules.command import CommandStage  # noqa: E402
from modules.loop_stage import GenerationLoopStage  # noqa: E402
from modules.scene import SceneStage  # noqa: E402

SCENE = 'scene8'
COMMAND = 'shake the test tube two times'

TUBE = 'transparent_test_tube_1'
CAP = 'yellow_test_tube_cap_1'


def tree(*actions):
    """A fenced create_behavior_tree() holding the given action lines."""
    names = [line.split('name="')[1].split('"')[0] for line in actions]
    variables = [f'node_{i}' for i, _ in enumerate(actions, start=1)]
    body = '\n'.join(f'        {variable} = {action}'
                     for variable, action in zip(variables, actions))
    return ('```python\n'
            'def create_behavior_tree():\n'
            '    try:\n'
            '        root = py_trees.composites.Sequence(name="Root", memory=True)\n'
            f'{body}\n'
            f'        root.add_children([{", ".join(variables)}])\n'
            '\n'
            '        return root\n'
            '    except Exception as e:\n'
            '        logging.error(f"Error in create_behavior_tree: {e}")\n'
            '```') if names else None


CLOSE = f'Close(name="CloseTube", obj="{TUBE}", closing_obj="{CAP}")'
SHAKE = f'Shake(name="ShakeTube", obj="{TUBE}", times=2)'
SHAKE_UNKNOWN = 'Shake(name="ShakeTube", obj="transparent_test_tube_9", times=2)'

GOOD_TREE = tree(CLOSE, SHAKE)
TREE_WITHOUT_CLOSE = tree(SHAKE)
TREE_WITH_WRONG_ID = tree(SHAKE_UNKNOWN)

ACCEPT = '{"verdict": "accept", "errors": [], "reason": ""}'
REJECT = ('{"verdict": "reject", "errors": ["tube is shaken while open"], '
          '"reason": "ShakeTube shakes an open tube that holds liquid."}')
NOT_A_FORM = 'Looks fine to me.'

NO_CODE = ('I can shake the test tube, but I would like to know how many times before '
           'I write the tree.')


class Scripted:
    """Stands in for modules.llm.ask and remembers every call."""

    def __init__(self, generator, judge):
        self.generator = list(generator)
        self.judge = list(judge)
        self.calls = []

    def __call__(self, system_prompt, text, model, temperature, logger, context=None,
                 image_path=None, tag='llm', response_format=None):
        who = 'judge' if 'judge' in tag else 'generator'
        queue = self.judge if who == 'judge' else self.generator
        assert queue, f'the {who} was called more often than the script allows'
        reply = queue.pop(0)
        self.calls.append({'who': who, 'tag': tag, 'message': text, 'reply': reply})
        return {'text': reply, 'usage': {}, 'seconds': 0.0, 'model': model,
                'artifacts': {}}

    def messages(self, who):
        return [call['message'] for call in self.calls if call['who'] == who]


@pytest.fixture
def run(monkeypatch, tmp_path):
    """Run the real pipeline with scripted replies, in a throwaway run folder."""
    monkeypatch.setattr(config, 'RUNS_DIR', tmp_path / 'runs')

    def go(generator_replies, judge_replies=(), judge_enabled=True):
        scripted = Scripted(generator_replies, judge_replies)
        monkeypatch.setattr(llm, 'ask', scripted)
        pipeline = Pipeline([SceneStage(), CommandStage(), GenerationLoopStage()])
        context = RunContext(scene=SCENE)
        payload = {'scene': SCENE, 'command': COMMAND,
                   'judge_enabled': judge_enabled}
        pipeline.run(context, payload)
        return payload['loop_record'], scripted, context

    return go


# --- 1-3: the judge decides ---------------------------------------------------

def test_good_tree_is_accepted(run):
    record, scripted, _ = run([GOOD_TREE], [ACCEPT])
    assert record['status'] == 'accepted'
    assert record['counts']['generator_calls'] == 1
    assert record['counts']['judge_calls'] == 1
    assert record['accepted_tree'] is not None


def test_rejected_tree_is_repaired(run):
    record, scripted, _ = run([TREE_WITHOUT_CLOSE, GOOD_TREE], [REJECT, ACCEPT])
    assert record['status'] == 'accepted'
    assert record['counts']['generator_calls'] == 2
    assert record['counts']['judge_rejections'] == 1

    second = scripted.messages('generator')[1]
    assert 'REVIEWER FINDINGS:' in second
    assert 'Problems: tube is shaken while open.' in second
    assert 'PREVIOUS TREE:' in second


def test_three_rejections_end_the_run(run):
    record, _, _ = run([TREE_WITHOUT_CLOSE] * 3, [REJECT] * 3)
    assert record['status'] == 'failed_judge_cap'
    assert record['counts']['generator_calls'] == 3
    assert record['counts']['judge_rejections'] == 3


# --- 4-5: the syntax check decides -------------------------------------------

def test_wrong_id_is_repaired(run):
    record, scripted, _ = run([TREE_WITH_WRONG_ID, GOOD_TREE], [ACCEPT])
    assert record['status'] == 'accepted'
    assert record['counts']['syntax_failures'] == 1

    second = scripted.messages('generator')[1]
    assert 'SYNTAX CHECK ERRORS:' in second
    assert 'transparent_test_tube_9' in second


def test_three_syntax_failures_end_the_run(run):
    record, scripted, _ = run([TREE_WITH_WRONG_ID] * 3, [])
    assert record['status'] == 'failed_syntax_cap'
    assert record['counts']['syntax_failures'] == 3
    assert record['counts']['judge_calls'] == 0
    assert not scripted.messages('judge')


# --- 6-7: a reply that holds no tree -----------------------------------------

def test_reply_without_code_is_sent_back(run):
    record, scripted, _ = run([NO_CODE, GOOD_TREE], [ACCEPT])
    assert record['status'] == 'accepted'
    assert record['counts']['syntax_failures'] == 1
    assert record['attempts'][0]['kind'] == 'no_code'

    second = scripted.messages('generator')[1]
    assert 'no create_behavior_tree() code block' in second
    # There was no tree to send back, only the demand for one.
    assert 'PREVIOUS TREE:' not in second


def test_three_replies_without_code_end_the_run(run):
    record, scripted, _ = run([NO_CODE] * 3, [])
    assert record['status'] == 'failed_syntax_cap'
    assert record['counts']['syntax_failures'] == 3
    assert record['counts']['judge_calls'] == 0
    assert not scripted.messages('judge')


# --- 9-10: the judge's own format --------------------------------------------

def test_invalid_form_is_retried(run):
    record, scripted, _ = run([GOOD_TREE], [NOT_A_FORM, ACCEPT])
    assert record['status'] == 'accepted'
    assert record['counts']['judge_calls'] == 2
    assert record['counts']['judge_format_errors'] == 1
    assert 'not a valid judgement form' in scripted.messages('judge')[1]


def test_three_invalid_forms_end_the_run(run):
    record, _, _ = run([GOOD_TREE], [NOT_A_FORM] * 3)
    assert record['status'] == 'judge_error'
    assert record['counts']['judge_calls'] == 3
    assert record['accepted_tree'] is None


# --- the baseline: no judge, no loop -----------------------------------------

def test_baseline_keeps_the_first_tree_unjudged(run):
    # The tree shakes an open tube, which the judge would reject. Nothing judges it.
    record, scripted, _ = run([TREE_WITHOUT_CLOSE], judge_enabled=False)
    assert record['status'] == 'no_judge'
    assert record['counts']['generator_calls'] == 1
    assert record['counts']['judge_calls'] == 0
    assert not scripted.messages('judge')
    assert record['accepted_tree'] is not None
    assert record['attempts'][0]['judge_form'] is None


def test_baseline_does_not_repair_a_syntax_failure(run):
    record, scripted, _ = run([TREE_WITH_WRONG_ID], judge_enabled=False)
    assert record['status'] == 'failed_syntax_cap'
    # One attempt only: with no judge there is nothing to repair towards.
    assert record['counts']['generator_calls'] == 1
    assert record['counts']['syntax_failures'] == 1


def test_baseline_does_not_ask_again_for_missing_code(run):
    record, _, _ = run([NO_CODE], judge_enabled=False)
    assert record['status'] == 'failed_syntax_cap'
    assert record['counts']['generator_calls'] == 1


# --- what the run leaves behind ----------------------------------------------

def test_every_attempt_keeps_its_own_folder(run):
    _, _, context = run([TREE_WITHOUT_CLOSE, GOOD_TREE], [REJECT, ACCEPT])
    for number in ('01', '02'):
        folder = context.directory / 'attempts' / number
        assert (folder / 'create_behavior_tree.py').exists()
        assert (folder / 'tester_report.json').exists()
        assert (folder / 'judge_form.json').exists()
    first = (context.directory / 'attempts/01/create_behavior_tree.py').read_text()
    second = (context.directory / 'attempts/02/create_behavior_tree.py').read_text()
    assert 'Close' not in first and 'Close' in second
