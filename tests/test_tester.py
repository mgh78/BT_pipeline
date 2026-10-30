"""The syntax check accepts the decorators and conditions the generation prompt allows.

    ../contextual-asr/venv/bin/python -m pytest tests -q
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from modules import tester  # noqa: E402
from modules.tester import SyntaxTestStage  # noqa: E402

FIND_TUBE = 'find_tube = FindOne(name="FindTube", key="tube", type="test tube")'
FIND_CAP = 'find_cap = FindOne(name="FindCap", key="cap", type="test tube cap")'
SHAKE = 'Shake(name="ShakeTube", obj="@tube", times=2)'
CLOSE = 'Close(name="CloseTube", obj="@tube", closing_obj="@cap")'


def code(*lines, root_children='close_1, shake_1'):
    """A create_behavior_tree() whose body is ``lines``, then the root's children.

    The tree always starts by finding the tube and its cap, so the actions can refer to
    them as "@tube" and "@cap".
    """
    body = '\n'.join(f'        {line}' for line in (FIND_TUBE, FIND_CAP, *lines))
    return ('def create_behavior_tree():\n'
            '    try:\n'
            '        root = py_trees.composites.Sequence(name="Root", memory=True)\n'
            f'{body}\n'
            f'        root.add_children([find_tube, find_cap, {root_children}])\n'
            '        return root\n'
            '    except Exception as e:\n'
            '        logging.error(f"Error in create_behavior_tree: {e}")\n')


def every_known_node():
    """The names of all decorators, behaviours and helpers the tester can check."""
    short = lambda table: tuple(name.rsplit('.', 1)[-1] for name in table)  # noqa: E731
    return (short(tester.DECORATOR_SIGNATURES), short(tester.BEHAVIOUR_SIGNATURES),
            short(tester.HELPER_SIGNATURES))


@pytest.fixture
def full_grammar(monkeypatch):
    """Allow every py_trees node the tester knows, not only the prompt's grammar."""
    decorators, behaviours, helpers = every_known_node()
    monkeypatch.setattr(config, 'GRAMMAR_DECORATORS', decorators)
    monkeypatch.setattr(config, 'GRAMMAR_BEHAVIOURS', behaviours)
    monkeypatch.setattr(config, 'GRAMMAR_HELPERS', helpers)


def run_checks(source):
    checks, tree, _ = SyntaxTestStage().check(source)
    return {check.id: check for check in checks}, tree


def failures(checks):
    return sorted(check_id for check_id, check in checks.items() if check.blocking)


def test_a_tree_with_a_retry_decorator_passes():
    checks, tree = run_checks(code(
        f'shake_1 = {SHAKE}',
        'retry_1 = py_trees.decorators.Retry(name="RetryShake", child=shake_1, '
        'num_failures=3)',
        root_children='retry_1'))
    assert failures(checks) == []
    assert type(tree.children[2]).__name__ == 'Retry'
    assert checks['build.node_count'].passed


def test_conditions_and_the_blackboard_pass(full_grammar):
    checks, tree = run_checks(code(
        'set_1 = py_trees.behaviours.SetBlackboardVariable(name="SetCapOn", '
        'variable_name="cap_on", variable_value=True, overwrite=True)',
        'check_1 = py_trees.common.ComparisonExpression(variable="cap_on", value=True, '
        'operator=lambda a, b: a == b)',
        'cond_1 = py_trees.behaviours.CheckBlackboardVariableValue(name="CapIsOn", '
        'check=check_1)',
        f'shake_1 = {SHAKE}',
        'guard_1 = py_trees.composites.Sequence(name="ShakeIfCapOn", memory=True)',
        'guard_1.add_children([cond_1, shake_1])',
        root_children='set_1, guard_1'))
    assert failures(checks) == []
    # The comparison is a helper object, not a node, so it must not break the count.
    assert checks['build.node_count'].passed


def test_a_decorator_inside_a_decorator_passes(full_grammar):
    checks, _ = run_checks(code(
        f'shake_1 = {SHAKE}',
        'timeout_1 = py_trees.decorators.Timeout(name="TimeoutShake", child=shake_1, '
        'duration=5)',
        'invert_1 = py_trees.decorators.Inverter(name="InvertShake", child=timeout_1)',
        root_children='invert_1'))
    assert failures(checks) == []


def test_an_unknown_decorator_is_not_allowed():
    checks, _ = run_checks(code(
        f'shake_1 = {SHAKE}',
        'odd_1 = py_trees.decorators.Teleport(name="OddShake", child=shake_1)',
        root_children='odd_1'))
    assert 'structure.allowed_nodes' in failures(checks)
    assert 'Teleport' in checks['structure.allowed_nodes'].message


def test_a_decorator_without_its_child_is_refused():
    checks, _ = run_checks(code(
        f'shake_1 = {SHAKE}',
        'retry_1 = py_trees.decorators.Retry(name="RetryShake", num_failures=3)',
        root_children='retry_1, shake_1'))
    assert 'arguments.signatures' in failures(checks)
    assert 'missing child' in checks['arguments.signatures'].message


def test_an_argument_the_decorator_does_not_take_is_refused():
    checks, _ = run_checks(code(
        f'shake_1 = {SHAKE}',
        'retry_1 = py_trees.decorators.Retry(name="RetryShake", child=shake_1, '
        'num_failures=3, delay=2)',
        root_children='retry_1'))
    assert 'arguments.signatures' in failures(checks)
    assert 'does not take delay' in checks['arguments.signatures'].message


def test_a_count_must_be_an_integer():
    checks, _ = run_checks(code(
        f'shake_1 = {SHAKE}',
        'retry_1 = py_trees.decorators.Retry(name="RetryShake", child=shake_1, '
        'num_failures="3")',
        root_children='retry_1'))
    assert 'arguments.counts' in failures(checks)
    assert 'num_failures' in checks['arguments.counts'].message


def test_a_decorators_child_cannot_also_be_a_composite_child():
    checks, _ = run_checks(code(
        f'shake_1 = {SHAKE}',
        'retry_1 = py_trees.decorators.Retry(name="RetryShake", child=shake_1, '
        'num_failures=3)',
        root_children='retry_1, shake_1'))
    assert 'structure.single_parent' in failures(checks)


def test_a_decorator_that_is_never_attached_is_an_orphan():
    checks, _ = run_checks(code(
        f'shake_1 = {SHAKE}',
        'retry_1 = py_trees.decorators.Retry(name="RetryShake", child=shake_1, '
        'num_failures=3)',
        root_children='shake_1'))
    assert 'structure.reachable' in failures(checks) or \
        'structure.single_parent' in failures(checks)


def test_the_four_actions_still_work_as_before():
    checks, _ = run_checks(code(
        f'close_1 = {CLOSE}', f'shake_1 = {SHAKE}'))
    assert failures(checks) == []


def test_decorators_and_behaviours_remember_their_arguments(full_grammar):
    checks, tree = run_checks(code(
        'set_1 = py_trees.behaviours.SetBlackboardVariable(name="SetCapOn", '
        'variable_name="cap_on", variable_value=True, overwrite=True)',
        'check_1 = py_trees.common.ComparisonExpression(variable="cap_on", value=True, '
        'operator=lambda a, b: a == b)',
        'cond_1 = py_trees.behaviours.CheckBlackboardVariableValue(name="CapIsOn", '
        'check=check_1)',
        f'shake_1 = {SHAKE}',
        'retry_1 = py_trees.decorators.Retry(name="RetryShake", child=shake_1, '
        'num_failures=3)',
        'status_1 = py_trees.decorators.Condition(name="WaitShake", child=retry_1, '
        'status=py_trees.common.Status.SUCCESS)',
        root_children='set_1, cond_1, status_1'))
    assert failures(checks) == []
    _, _, set_1, cond_1, status_1 = tree.children
    assert set_1.arguments == {'variable_name': 'cap_on', 'variable_value': True,
                               'overwrite': True}
    assert cond_1.arguments == {
        'check': "ComparisonExpression(variable='cap_on', value=True, "
                 "operator=lambda a, b: a == b)"}
    assert status_1.arguments == {'status': 'Status.SUCCESS'}
    assert status_1.children[0].arguments == {'num_failures': 3}
    assert type(status_1).__name__ == 'Condition'      # the class keeps its own name


def test_the_text_outline_marks_decorators():
    from modules.tester import _as_text
    _, tree = run_checks(code(
        f'shake_1 = {SHAKE}',
        'retry_1 = py_trees.decorators.Retry(name="RetryShake", child=shake_1, '
        'num_failures=3)',
        root_children='retry_1'))
    outline = _as_text(tree)
    assert '◇ RetryShake  (num_failures=3)' in outline
    assert outline.index('RetryShake') < outline.index('ShakeTube')


def test_the_judge_outline_shows_decorators_and_conditions(full_grammar):
    from modules.loop import outline_for_judge
    _, tree = run_checks(code(
        'set_1 = py_trees.behaviours.SetBlackboardVariable(name="SetShaken", '
        'variable_name="shaken", variable_value=True, overwrite=True)',
        f'shake_1 = {SHAKE}',
        'retry_1 = py_trees.decorators.Retry(name="RetryShake", child=shake_1, '
        'num_failures=3)',
        'invert_1 = py_trees.decorators.Inverter(name="NotShaken", child=retry_1)',
        root_children='set_1, invert_1'))
    assert outline_for_judge(tree).splitlines() == [
        'Sequence [Root]',
        '    FindOne(key="tube", type="test tube") [FindTube]',
        '    FindOne(key="cap", type="test tube cap") [FindCap]',
        '    SetBlackboardVariable(variable_name="shaken", variable_value=true, '
        'overwrite=true) [SetShaken]',
        '    Inverter [NotShaken]',
        '        Retry(num_failures=3) [RetryShake]',
                '            Shake(obj="@tube", times=2) [ShakeTube]',
    ]


# --- the grammar is the one in config, which follows the prompt -------------------

def test_the_four_decorators_of_the_prompt_pass():
    for name, extra in (('Retry', 'num_failures=3'), ('Repeat', 'num_success=2'),
                        ('Timeout', 'duration=5'), ('FailureIsSuccess', '')):
        arguments = f'name="Wrap", child=shake_1{", " + extra if extra else ""}'
        checks, tree = run_checks(code(
            f'shake_1 = {SHAKE}',
            f'wrap_1 = py_trees.decorators.{name}({arguments})',
            root_children='wrap_1'))
        assert failures(checks) == [], name
        assert type(tree.children[2]).__name__ == name


def test_a_decorator_the_prompt_does_not_name_is_not_allowed():
    checks, _ = run_checks(code(
        f'shake_1 = {SHAKE}',
        'invert_1 = py_trees.decorators.Inverter(name="NotShake", child=shake_1)',
        root_children='invert_1'))
    assert failures(checks) == ['structure.allowed_nodes']
    assert 'py_trees.decorators.Inverter' in checks['structure.allowed_nodes'].message


def test_the_prompt_has_no_conditions_so_they_are_not_allowed():
    checks, _ = run_checks(code(
        f'shake_1 = {SHAKE}',
        'set_1 = py_trees.behaviours.SetBlackboardVariable(name="SetFlag", '
        'variable_name="flag", variable_value=True, overwrite=True)',
        root_children='shake_1, set_1'))
    assert 'structure.allowed_nodes' in failures(checks)
    assert 'SetBlackboardVariable' in checks['structure.allowed_nodes'].message


def test_the_grammar_follows_the_config(monkeypatch):
    monkeypatch.setattr(config, 'GRAMMAR_DECORATORS',
                        (*config.GRAMMAR_DECORATORS, 'Inverter'))
    checks, _ = run_checks(code(
        f'shake_1 = {SHAKE}',
        'invert_1 = py_trees.decorators.Inverter(name="NotShake", child=shake_1)',
        root_children='invert_1'))
    assert failures(checks) == []
