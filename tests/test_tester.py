"""The syntax check accepts the decorators and conditions the generation prompt allows.

    ../contextual-asr/venv/bin/python -m pytest tests -q
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.scene import load_scene  # noqa: E402
from modules.tester import SyntaxTestStage  # noqa: E402

TUBE = 'transparent_test_tube_1'
CAP = 'yellow_test_tube_cap_1'
SHAKE = f'Shake(name="ShakeTube", obj="{TUBE}", times=2)'
CLOSE = f'Close(name="CloseTube", obj="{TUBE}", closing_obj="{CAP}")'


def code(*lines, root_children='close_1, shake_1'):
    """A create_behavior_tree() whose body is ``lines``, then the root's children."""
    body = '\n'.join(f'        {line}' for line in lines)
    return ('def create_behavior_tree():\n'
            '    try:\n'
            '        root = py_trees.composites.Sequence(name="Root", memory=True)\n'
            f'{body}\n'
            f'        root.add_children([{root_children}])\n'
            '        return root\n'
            '    except Exception as e:\n'
            '        logging.error(f"Error in create_behavior_tree: {e}")\n')


@pytest.fixture(scope='module')
def scene():
    return load_scene('scene8')


def run_checks(source, scene):
    checks, tree, _ = SyntaxTestStage().check(source, scene)
    return {check.id: check for check in checks}, tree


def failures(checks):
    return sorted(check_id for check_id, check in checks.items() if check.blocking)


def test_a_tree_with_a_retry_decorator_passes(scene):
    checks, tree = run_checks(code(
        f'shake_1 = {SHAKE}',
        'retry_1 = py_trees.decorators.Retry(name="RetryShake", child=shake_1, '
        'num_failures=3)',
        root_children='retry_1'), scene)
    assert failures(checks) == []
    assert type(tree.children[0]).__name__ == 'Retry'
    assert checks['build.node_count'].passed


def test_conditions_and_the_blackboard_pass(scene):
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
        root_children='set_1, guard_1'), scene)
    assert failures(checks) == []
    # The comparison is a helper object, not a node, so it must not break the count.
    assert checks['build.node_count'].passed


def test_a_decorator_inside_a_decorator_passes(scene):
    checks, _ = run_checks(code(
        f'shake_1 = {SHAKE}',
        'timeout_1 = py_trees.decorators.Timeout(name="TimeoutShake", child=shake_1, '
        'duration=5)',
        'invert_1 = py_trees.decorators.Inverter(name="InvertShake", child=timeout_1)',
        root_children='invert_1'), scene)
    assert failures(checks) == []


def test_an_unknown_decorator_is_not_allowed(scene):
    checks, _ = run_checks(code(
        f'shake_1 = {SHAKE}',
        'odd_1 = py_trees.decorators.Teleport(name="OddShake", child=shake_1)',
        root_children='odd_1'), scene)
    assert 'structure.allowed_nodes' in failures(checks)
    assert 'Teleport' in checks['structure.allowed_nodes'].message


def test_a_decorator_without_its_child_is_refused(scene):
    checks, _ = run_checks(code(
        f'shake_1 = {SHAKE}',
        'retry_1 = py_trees.decorators.Retry(name="RetryShake", num_failures=3)',
        root_children='retry_1, shake_1'), scene)
    assert 'arguments.signatures' in failures(checks)
    assert 'missing child' in checks['arguments.signatures'].message


def test_an_argument_the_decorator_does_not_take_is_refused(scene):
    checks, _ = run_checks(code(
        f'shake_1 = {SHAKE}',
        'retry_1 = py_trees.decorators.Retry(name="RetryShake", child=shake_1, '
        'num_failures=3, delay=2)',
        root_children='retry_1'), scene)
    assert 'arguments.signatures' in failures(checks)
    assert 'does not take delay' in checks['arguments.signatures'].message


def test_a_count_must_be_an_integer(scene):
    checks, _ = run_checks(code(
        f'shake_1 = {SHAKE}',
        'retry_1 = py_trees.decorators.Retry(name="RetryShake", child=shake_1, '
        'num_failures="3")',
        root_children='retry_1'), scene)
    assert 'arguments.counts' in failures(checks)
    assert 'num_failures' in checks['arguments.counts'].message


def test_a_decorators_child_cannot_also_be_a_composite_child(scene):
    checks, _ = run_checks(code(
        f'shake_1 = {SHAKE}',
        'retry_1 = py_trees.decorators.Retry(name="RetryShake", child=shake_1, '
        'num_failures=3)',
        root_children='retry_1, shake_1'), scene)
    assert 'structure.single_parent' in failures(checks)


def test_a_decorator_that_is_never_attached_is_an_orphan(scene):
    checks, _ = run_checks(code(
        f'shake_1 = {SHAKE}',
        'retry_1 = py_trees.decorators.Retry(name="RetryShake", child=shake_1, '
        'num_failures=3)',
        root_children='shake_1'), scene)
    assert 'structure.reachable' in failures(checks) or \
        'structure.single_parent' in failures(checks)


def test_the_four_actions_still_work_as_before(scene):
    checks, _ = run_checks(code(
        f'close_1 = {CLOSE}', f'shake_1 = {SHAKE}'), scene)
    assert failures(checks) == []


def test_decorators_and_behaviours_remember_their_arguments(scene):
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
        root_children='set_1, cond_1, status_1'), scene)
    assert failures(checks) == []
    set_1, cond_1, status_1 = tree.children
    assert set_1.arguments == {'variable_name': 'cap_on', 'variable_value': True,
                               'overwrite': True}
    assert cond_1.arguments == {
        'check': "ComparisonExpression(variable='cap_on', value=True, "
                 "operator=lambda a, b: a == b)"}
    assert status_1.arguments == {'status': 'Status.SUCCESS'}
    assert status_1.children[0].arguments == {'num_failures': 3}
    assert type(status_1).__name__ == 'Condition'      # the class keeps its own name


def test_the_text_outline_marks_decorators(scene):
    from modules.tester import _as_text
    _, tree = run_checks(code(
        f'shake_1 = {SHAKE}',
        'retry_1 = py_trees.decorators.Retry(name="RetryShake", child=shake_1, '
        'num_failures=3)',
        root_children='retry_1'), scene)
    outline = _as_text(tree)
    assert '◇ RetryShake  (num_failures=3)' in outline
    assert outline.index('RetryShake') < outline.index('ShakeTube')


def test_the_judge_outline_shows_decorators_and_conditions(scene):
    from modules.loop import outline_for_judge
    _, tree = run_checks(code(
        'set_1 = py_trees.behaviours.SetBlackboardVariable(name="SetShaken", '
        'variable_name="shaken", variable_value=True, overwrite=True)',
        f'shake_1 = {SHAKE}',
        'retry_1 = py_trees.decorators.Retry(name="RetryShake", child=shake_1, '
        'num_failures=3)',
        'invert_1 = py_trees.decorators.Inverter(name="NotShaken", child=retry_1)',
        root_children='set_1, invert_1'), scene)
    assert outline_for_judge(tree).splitlines() == [
        'Sequence [Root]',
        '    SetBlackboardVariable(variable_name="shaken", variable_value=true, '
        'overwrite=true) [SetShaken]',
        '    Inverter [NotShaken]',
        '        Retry(num_failures=3) [RetryShake]',
        f'            Shake(obj="{TUBE}", times=2) [ShakeTube]',
    ]
