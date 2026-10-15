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
REJECT = ('{"verdict": "reject", "errors": ["missing_precondition"], '
          '"reason": "ShakeTube shakes an open tube that holds liquid."}')
NOT_A_FORM = 'Looks fine to me.'

QUESTION = 'CLARIFY: How many times should I shake the test tube?'


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

    def go(generator_replies, judge_replies=(), answers=()):
        scripted = Scripted(generator_replies, judge_replies)
        monkeypatch.setattr(llm, 'ask', scripted)
        pipeline = Pipeline([SceneStage(), CommandStage(), GenerationLoopStage()])
        context = RunContext(scene=SCENE)
        payload = {'scene': SCENE, 'command': COMMAND,
                   'clarification_answers': list(answers)}
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
    assert 'A necessary precondition or check is missing' in second
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


# --- 6-8: questions ----------------------------------------------------------

def test_question_then_answer_then_tree(run):
    record, scripted, _ = run([QUESTION, GOOD_TREE], [ACCEPT], answers=['two times'])
    assert record['status'] == 'accepted'
    assert record['counts']['clarifications'] == 1

    judge_message = scripted.messages('judge')[0]
    assert 'CLARIFICATION:' in judge_message
    assert 'two times' in judge_message


def test_question_without_an_answer_stops_the_run(run):
    record, _, _ = run([QUESTION], [])
    assert record['status'] == 'no_answer'
    assert record['attempts'][-1]['question'].startswith('How many times')


def test_three_questions_end_the_run(run):
    record, _, _ = run([QUESTION] * 3, [], answers=['two times', 'the left one'])
    assert record['status'] == 'failed_clarification_cap'
    assert record['counts']['clarifications'] == 3


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
