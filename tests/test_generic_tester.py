"""The syntax check understands the nodes of the generic prompt and their properties.

    ../contextual-asr/venv/bin/python -m pytest tests -q
"""

import pytest

from generic_trees import RACK, code, failures, flasks_into_rack, run_checks


def test_a_generic_tree_passes():
    checks, tree = run_checks(flasks_into_rack())
    assert failures(checks) == []
    assert [child.name for child in tree.children] == [
        'FindRack', 'FindFlasks', 'ForEachFlask']


def test_find_nodes_remember_what_they_describe():
    _, tree = run_checks(flasks_into_rack())
    rack, flasks, loop = tree.children
    assert rack.arguments == {'key': 'rack', 'type': 'box', 'color': 'blue'}
    assert flasks.arguments == {'key': 'flasks', 'type': 'measuring cylinder'}
    assert loop.arguments == {'source_key': 'flasks', 'target_key': 'flask'}
    assert loop.children[0].arguments == {'obj': '@flask', 'location': '@rack'}


def test_a_find_node_may_pick_the_nth_from_an_end():
    checks, _ = run_checks(code(
        'find_1 = FindOne(name="FindSecondBox", key="box", type="box", '
        'position="leftmost", nth=2)',
        'find_2 = FindAll(name="FindRightCubes", key="cubes", type="cube", '
        'position="rightmost", limit=2)',
        root_children='find_1, find_2'))
    assert failures(checks) == []


def test_has_property_passes():
    checks, _ = run_checks(code(
        RACK,
        'has_1 = HasProperty(name="RackIsBlue", obj="@rack", property="color", '
        'value="blue")',
        root_children='find_1, has_1'))
    assert failures(checks) == []


@pytest.mark.parametrize('arguments, message', [
    ('type="bolt"', 'not a type the robot perceives'),
    ('color="Blue"', 'lowercase colour name'),
    ('graspable="yes"', 'must be True or False'),
    ('type="box", position="middle"', 'position='),
    ('type="box", nth=0', 'positive integer'),
    ('type="box", nth="2"', 'positive integer'),
])
def test_a_find_node_with_a_value_the_robot_does_not_have_is_refused(arguments, message):
    checks, _ = run_checks(code(
        f'find_1 = FindOne(name="FindBox", key="box", {arguments})',
        root_children='find_1'))
    assert failures(checks) == ['objects.properties']
    assert message in checks['objects.properties'].message


def test_a_property_the_robot_does_not_perceive_is_refused():
    checks, _ = run_checks(code(
        'find_1 = FindOne(name="FindBox", key="box", shape="round")',
        root_children='find_1'))
    assert failures(checks) == ['arguments.signatures']
    assert 'shape' in checks['arguments.signatures'].message


def test_a_find_node_needs_a_key():
    checks, _ = run_checks(code(
        'find_1 = FindOne(name="FindBox", type="box")', root_children='find_1'))
    assert failures(checks) == ['arguments.signatures']


def test_findall_takes_limit_not_nth():
    checks, _ = run_checks(code(
        'find_1 = FindAll(name="FindBoxes", key="boxes", type="box", nth=2)',
        root_children='find_1'))
    assert failures(checks) == ['arguments.signatures']


@pytest.mark.parametrize('arguments', [
    'property="shape", value="round"',
    'property="color", value=3',
    'property="closed", value="yes"',
    'property="type", value="bolt"',
])
def test_has_property_with_a_wrong_property_or_value_is_refused(arguments):
    checks, _ = run_checks(code(
        RACK,
        f'has_1 = HasProperty(name="Check", obj="@rack", {arguments})',
        root_children='find_1, has_1'))
    assert failures(checks) == ['objects.properties']

