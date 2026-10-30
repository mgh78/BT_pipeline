"""The syntax check understands the nodes of the generic prompt and their properties.

    ../contextual-asr/venv/bin/python -m pytest tests -q
"""

import pytest

from generic_trees import (FLASKS, LOOP, PLACE, RACK, code, failures, flasks_into_rack,
                           run_checks)


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
    assert failures(checks) == ['arguments.signatures', 'objects.keys']


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



# --- keys and @references ---------------------------------------------------------

def refused(source, check_id, text):
    checks, _ = run_checks(source)
    assert check_id in failures(checks), checks[check_id].message
    assert text in checks[check_id].message


def test_a_key_is_a_plain_name():
    refused(code('find_1 = FindOne(name="FindBox", key="@box", type="box")',
                 root_children='find_1'), 'objects.keys', 'plain name')


def test_a_key_is_stored_once():
    refused(code(RACK, 'find_2 = FindOne(name="FindOtherBox", key="rack", type="crate")',
                 root_children='find_1, find_2'), 'objects.keys', 'already stored')


def test_an_object_is_written_as_an_at_reference():
    refused(code(RACK, 'place_1 = Place(name="PlaceIt", obj="blue_box_1", location="@rack")',
                 root_children='find_1, place_1'), 'objects.references', 'not an @ reference')


def test_an_unknown_key_is_refused():
    refused(code(RACK, 'place_1 = Place(name="PlaceIt", obj="@cube", location="@rack")',
                 root_children='find_1, place_1'), 'objects.references',
            'no node stores "cube"')


def test_a_key_cannot_be_used_before_it_is_stored():
    refused(code('find_2 = FindOne(name="FindCube", key="cube", type="cube")',
                 'place_1 = Place(name="PlaceIt", obj="@cube", location="@rack")',
                 RACK, root_children='find_2, place_1, find_1'),
            'objects.references', 'after this node runs')


def test_a_list_cannot_be_placed():
    refused(code(RACK, FLASKS,
                 'place_1 = Place(name="PlaceIt", obj="@flasks", location="@rack")',
                 root_children='find_1, find_2, place_1'),
            'objects.references', 'holds a list')


def test_foreach_loops_over_a_list_not_one_object():
    refused(code(RACK, PLACE,
                 'for_1 = py_trees.decorators.ForEach(name="ForEachBox", child=place_1, '
                 'source_key="rack", target_key="flask")',
                 root_children='find_1, for_1'),
            'objects.references', 'holds one object')


def test_the_loop_target_only_exists_inside_the_loop():
    refused(code(RACK, FLASKS, PLACE, LOOP,
                 'place_2 = Place(name="PlaceAgain", obj="@flask", location="@rack")',
                 root_children='find_1, find_2, for_1, place_2'),
            'objects.references', 'only be used inside it')


def test_the_loop_needs_its_list_first():
    refused(code(RACK, PLACE, LOOP, FLASKS, root_children='find_1, for_1, find_2'),
            'objects.references', 'after this node runs')


def test_a_condition_inside_the_loop_can_test_the_item():
    checks, _ = run_checks(code(
        RACK, FLASKS,
        'has_1 = HasProperty(name="FlaskHoldsLiquid", obj="@flask", '
        'property="holds_liquid", value=True)',
        PLACE,
        'seq_1 = py_trees.composites.Sequence(name="PlaceIfFull", memory=True)',
        'seq_1.add_children([has_1, place_1])',
        'skip_1 = py_trees.behaviours.Success(name="LeaveFlask")',
        'pick_1 = py_trees.composites.Selector(name="FullOrNot", memory=True)',
        'pick_1.add_children([seq_1, skip_1])',
        'for_1 = py_trees.decorators.ForEach(name="ForEachFlask", child=pick_1, '
        'source_key="flasks", target_key="flask")',
        root_children='find_1, find_2, for_1'))
    assert failures(checks) == []


def test_no_spill_label_for_a_tree_that_finds_its_objects():
    from modules.scene import load_scene
    from modules.tester import SyntaxTestStage, spill_label
    _, _, analysis = SyntaxTestStage().check(code(
        'find_1 = FindOne(name="FindTube", key="tube", type="test tube")',
        'shake_1 = Shake(name="ShakeTube", obj="@tube", times=2)',
        root_children='find_1, shake_1'))
    assert spill_label(analysis, load_scene('scene8')) is None
