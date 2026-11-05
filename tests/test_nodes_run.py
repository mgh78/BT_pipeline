"""The tree's nodes acting on a world: every node, built with bt_nodes.registry(world).

    ../contextual-asr/venv/bin/python -m pytest tests -q
"""

import os
import sys

import py_trees
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules import bt_nodes, xml_tree  # noqa: E402
from modules.mock_world import MockWorld  # noqa: E402
from modules.world import WorldObject  # noqa: E402

SUCCESS = py_trees.common.Status.SUCCESS
FAILURE = py_trees.common.Status.FAILURE


def document(*nodes):
    body = '\n'.join(f'      {node}' for node in nodes)
    return ('<root main_tree_to_execute="MainTree">\n'
            '  <BehaviorTree ID="MainTree">\n'
            '    <Sequence name="Root" memory="true">\n'
            f'{body}\n'
            '    </Sequence>\n'
            '  </BehaviorTree>\n'
            '</root>\n')


def thing(id, type, x, y, **fields):
    fields.setdefault('color', 'white')
    return WorldObject(id=id, type=type, position={'x': x, 'y': y, 'z': 0.0}, **fields)


def table():
    return MockWorld([
        thing('left_cube', 'cube', 0.3, -0.2, color='red'),
        thing('middle_cube', 'cube', 0.5, 0.0, color='dark green', marked=True),
        thing('right_cube', 'cube', 0.1, 0.2, color='red'),
        thing('box', 'box', 0.7, 0.3, color='blue', graspable=False),
        thing('tube', 'test tube', 0.4, 0.1, color='transparent',
              holds_liquid=True, liquid_color='transparent red'),
        thing('cap', 'test tube cap', 0.6, 0.1, color='yellow'),
    ])


@pytest.fixture(autouse=True)
def empty_blackboard():
    py_trees.blackboard.Blackboard.clear()
    yield
    py_trees.blackboard.Blackboard.clear()


def run(world, *nodes):
    """Tick the tree until it finishes; return its root and the node by name."""
    root = xml_tree.build_tree(document(*nodes), bt_nodes.registry(world))
    tree = py_trees.trees.BehaviourTree(root)
    for _ in range(50):
        tree.tick()
        if root.status != py_trees.common.Status.RUNNING:
            break
    return root, {node.name: node for node in root.iterate()}


def stored(key):
    return py_trees.blackboard.Blackboard.storage[f'/{key}']


FIND_CUBE = '<FindOne name="FindCube" key="cube" type="cube"/>'
FIND_BOX = '<FindOne name="FindBox" key="box" type="box"/>'
FIND_TUBE = '<FindOne name="FindTube" key="tube" type="test tube"/>'
FIND_CAP = '<FindOne name="FindCap" key="cap" type="test tube cap"/>'


# --- the trap of registry() ---------------------------------------------------------

def test_the_parser_converts_the_attributes_to_their_types():
    _, nodes = run(table(),
                   '<FindAll name="FindSome" key="some" marked="False" limit="2"/>')
    node = nodes['FindSome']
    assert node.properties['marked'] is False
    assert node.limit == 2 and isinstance(node.limit, int)
    assert [o.id for o in stored('some')] == ['left_cube', 'tube']     # scan order, then the limit


def test_the_registry_keeps_the_tags_and_the_classes():
    built = bt_nodes.registry(table())
    assert set(built) == set(bt_nodes.REGISTRY)
    for tag, cls in built.items():
        assert cls.__name__ == tag and issubclass(cls, bt_nodes.REGISTRY[tag])
    assert bt_nodes._Node.world is None and bt_nodes.Place.world is None


# --- find nodes ----------------------------------------------------------------------

@pytest.mark.parametrize('attributes, expected', [
    ('', 'left_cube'),
    ('nth="2"', 'middle_cube'),
    ('position="rightmost"', 'right_cube'),
    ('position="nearest" nth="2"', 'left_cube'),
])
def test_find_one_stores_the_right_object(attributes, expected):
    root, _ = run(table(), f'<FindOne name="Find" key="found" type="cube" {attributes}/>')
    assert root.status == SUCCESS and stored('found').id == expected


def test_find_one_fails_when_too_few_match():
    root, nodes = run(table(), '<FindOne name="Find" key="found" type="cube" nth="4"/>')
    assert root.status == FAILURE
    assert 'found only 3 object(s)' in nodes['Find'].feedback_message
    assert '/found' not in py_trees.blackboard.Blackboard.storage


def test_find_all_stores_a_list():
    root, _ = run(table(), '<FindAll name="Find" key="found" color="red"/>')
    assert root.status == SUCCESS
    assert [o.id for o in stored('found')] == ['left_cube', 'right_cube']


def test_find_all_may_store_an_empty_list():
    root, _ = run(table(), '<FindAll name="Find" key="found" type="cup"/>')
    assert root.status == SUCCESS and stored('found') == []


# --- conditions ----------------------------------------------------------------------

@pytest.mark.parametrize('count, comparison, status', [
    (3, 'exactly', SUCCESS), (2, 'exactly', FAILURE),
    (3, 'at least', SUCCESS), (4, 'at least', FAILURE),
    (3, 'at most', SUCCESS), (2, 'at most', FAILURE),
])
def test_has_count(count, comparison, status):
    root, _ = run(table(), '<FindAll name="Find" key="found" type="cube"/>',
                  f'<HasCount name="Count" key="found" count="{count}" comparison="{comparison}"/>')
    assert root.status == status


def test_has_count_compares_exactly_by_default():
    root, _ = run(table(), '<FindAll name="Find" key="found" type="cube"/>',
                  '<HasCount name="Count" key="found" count="3"/>')
    assert root.status == SUCCESS


@pytest.mark.parametrize('prop, value, status', [
    ('marked', 'True', SUCCESS),
    ('marked', 'False', FAILURE),
    ('marked', 'false', FAILURE),
    ('color', 'green', SUCCESS),       # dark green matches loosely
    ('color', 'dark', FAILURE),
    ('type', 'cube', SUCCESS),
])
def test_has_property(prop, value, status):
    root, _ = run(table(), '<FindOne name="Find" key="found" marked="True"/>',
                  f'<HasProperty name="Check" obj="{{found}}" property="{prop}" value="{value}"/>')
    assert root.status == status


def test_has_property_compares_a_false_value():
    root, _ = run(table(), FIND_CUBE,
                  '<HasProperty name="Check" obj="{cube}" property="marked" value="False"/>')
    assert root.status == SUCCESS


def test_has_property_sees_the_table_as_it_is_now():
    root, _ = run(table(), FIND_TUBE, FIND_CAP,
                  '<Close name="CloseTube" obj="{tube}" closing_obj="{cap}"/>',
                  '<HasProperty name="Check" obj="{tube}" property="closed" value="True"/>')
    assert root.status == SUCCESS


# --- actions -------------------------------------------------------------------------

def test_place_acts_through_the_world():
    world = table()
    root, nodes = run(world, FIND_CUBE, FIND_BOX,
                      '<Place name="PlaceCube" obj="{cube}" location="{box}"/>')
    assert root.status == SUCCESS
    assert world.perceive({'on': 'box'})[0].id == 'left_cube'
    assert nodes['PlaceCube'].feedback_message == 'placed left_cube in box'


def test_place_fails_with_the_worlds_reason():
    root, nodes = run(table(), FIND_CUBE, FIND_BOX,
                      '<Place name="PlaceBox" obj="{box}" location="{cube}"/>')
    assert root.status == FAILURE
    assert nodes['PlaceBox'].feedback_message == 'box is fixed and cannot be grasped'


def test_pour_acts_through_the_world():
    world = table()
    root, nodes = run(world, FIND_TUBE, FIND_BOX,
                      '<Pour name="PourTube" source="{tube}" target="{box}"/>')
    assert root.status == SUCCESS
    assert world.perceive({'type': 'box'})[0].liquid_color == 'transparent red'
    assert nodes['PourTube'].feedback_message == 'poured tube into box'


def test_pour_fails_with_the_worlds_reason():
    root, nodes = run(table(), FIND_CUBE, FIND_BOX,
                      '<Pour name="PourCube" source="{cube}" target="{box}"/>')
    assert root.status == FAILURE
    assert nodes['PourCube'].feedback_message == 'left_cube holds no liquid'


def test_shake_carried_out_with_a_spill_succeeds_and_says_so():
    world = table()
    root, nodes = run(world, FIND_TUBE, '<Shake name="ShakeTube" obj="{tube}" times="2"/>')
    assert root.status == SUCCESS
    assert nodes['ShakeTube'].feedback_message == 'tube was shaken while open and spilled'
    assert world.snapshot()['faults'][0]['fault'] == 'spill'


def test_shake_fails_with_the_worlds_reason():
    root, nodes = run(table(), FIND_BOX, '<Shake name="ShakeBox" obj="{box}" times="2"/>')
    assert root.status == FAILURE
    assert nodes['ShakeBox'].feedback_message == 'box is fixed and cannot be grasped'


def test_close_acts_through_the_world():
    world = table()
    root, nodes = run(world, FIND_TUBE, FIND_CAP,
                      '<Close name="CloseTube" obj="{tube}" closing_obj="{cap}"/>')
    assert root.status == SUCCESS
    assert world.perceive({'type': 'test tube'})[0].closed_by == 'cap'
    assert nodes['CloseTube'].feedback_message == 'closed tube with cap'


def test_close_fails_with_the_worlds_reason():
    root, nodes = run(table(), FIND_TUBE, FIND_CUBE,
                      '<Close name="CloseTube" obj="{tube}" closing_obj="{cube}"/>')
    assert root.status == FAILURE
    assert nodes['CloseTube'].feedback_message == 'left_cube is not a cap or lid that fits tube'


# --- worlds --------------------------------------------------------------------------

def test_a_node_built_without_a_world_cannot_be_ticked():
    root = xml_tree.build_tree(document(FIND_CUBE))
    tree = py_trees.trees.BehaviourTree(root)
    with pytest.raises(RuntimeError, match='FindCube was built without a world; build the tree '
                                           r'with bt_nodes\.registry\(world\)'):
        tree.tick()


def test_two_trees_do_not_share_a_world():
    first_world, second_world = table(), table()
    place = '<Place name="PlaceCube" obj="{cube}" location="{box}"/>'
    first = xml_tree.build_tree(document(FIND_CUBE, FIND_BOX, place),
                                bt_nodes.registry(first_world))
    second = xml_tree.build_tree(document(FIND_CUBE, FIND_BOX, place),
                                 bt_nodes.registry(second_world))
    py_trees.trees.BehaviourTree(first).tick()
    assert first_world.perceive({'on': 'box'})
    assert not second_world.perceive({'on': 'box'})
    assert first.children[0].world is first_world
    assert second.children[0].world is second_world


def test_building_for_the_check_stores_nothing():
    checks, _, _ = xml_tree.check_xml(document(FIND_CUBE))
    assert xml_tree.passed(checks)
    assert py_trees.blackboard.Blackboard.storage == {}
