"""The XML syntax check: the generic trees of tests/generic_trees.py, written as XML.

Goes to ``tests/test_xml_tree.py`` and replaces ``tests/test_generic_tester.py``.

    ../contextual-asr/venv/bin/python -m pytest tests -q
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from modules import bt_nodes, loop, xml_tree  # noqa: E402


def document(*nodes):
    """An XML tree whose root Sequence holds ``nodes``."""
    body = '\n'.join(f'      {node}' for node in nodes)
    return ('<root main_tree_to_execute="MainTree">\n'
            '  <BehaviorTree ID="MainTree">\n'
            '    <Sequence name="Root" memory="true">\n'
            f'{body}\n'
            '    </Sequence>\n'
            '  </BehaviorTree>\n'
            '</root>\n')


def run_checks(text):
    checks, tree, _ = xml_tree.check_xml(text)
    return {check.id: check for check in checks}, tree


def failures(checks):
    return sorted(check_id for check_id, check in checks.items() if check.blocking)


RACK = '<FindOne name="FindRack" key="rack" type="box" color="blue"/>'
FLASKS = '<FindAll name="FindFlasks" key="flasks" type="measuring cylinder"/>'
LOOP = ('<ForEach name="ForEachFlask" source_key="flasks" target_key="flask">'
        '<Place name="PlaceFlask" obj="{flask}" location="{rack}"/></ForEach>')

# "If there are two glass objects, pour the one with green liquid into the yellow box; if
# there are three, pour the one with red liquid into the yellow box."
GLASS_BY_COUNT = '''<root main_tree_to_execute="MainTree">
  <BehaviorTree ID="MainTree">
    <Sequence name="Root" memory="true">
      <FindAll name="FindGlassObjects" key="glass_objects" color="transparent"/>
      <Selector name="ChooseByGlassObjectCount" memory="true">
        <Sequence name="TwoGlassObjectsCase" memory="true">
          <HasCount name="TwoGlassObjects" key="glass_objects" count="2"/>
          <FindOne name="FindGreenLiquidObject" key="green_object" color="transparent" liquid_color="green"/>
          <FindOne name="FindYellowBox" key="yellow_box" type="box" color="yellow"/>
          <Pour name="PourGreenIntoYellowBox" source="{green_object}" target="{yellow_box}"/>
        </Sequence>
        <Sequence name="ThreeGlassObjectsCase" memory="true">
          <HasCount name="ThreeGlassObjects" key="glass_objects" count="3"/>
          <FindOne name="FindRedLiquidObject" key="red_object" color="transparent" liquid_color="red"/>
          <FindOne name="FindYellowBoxAgain" key="yellow_box_2" type="box" color="yellow"/>
          <Pour name="PourRedIntoYellowBox" source="{red_object}" target="{yellow_box_2}"/>
        </Sequence>
        <Sequence name="NoCaseApplies" memory="true">
          <Inverter name="NotTwoGlassObjects">
            <HasCount name="TwoGlassObjectsCheck" key="glass_objects" count="2"/>
          </Inverter>
          <Inverter name="NotThreeGlassObjects">
            <HasCount name="ThreeGlassObjectsCheck" key="glass_objects" count="3"/>
          </Inverter>
        </Sequence>
      </Selector>
    </Sequence>
  </BehaviorTree>
</root>
'''


# --- Trees that pass -----------------------------------------------------------

def test_a_generic_tree_passes_and_builds():
    checks, tree = run_checks(document(RACK, FLASKS, LOOP))
    assert failures(checks) == []
    assert not any(not c.passed for c in checks.values())     # no warnings either
    assert [child.name for child in tree.children] == ['FindRack', 'FindFlasks',
                                                       'ForEachFlask']


def test_the_reference_choice_tree_passes():
    checks, tree = run_checks(GLASS_BY_COUNT)
    assert failures(checks) == []
    assert type(tree.children[1]).__name__ == 'Selector'


def test_built_nodes_carry_their_xml_name_and_typed_arguments():
    _, tree = run_checks(document(
        RACK, FLASKS,
        '<ForEach name="ForEachFlask" source_key="flasks" target_key="flask">'
        '<Retry name="RetryShake" num_failures="2">'
        '<Shake name="ShakeFlask" obj="{flask}" times="3"/></Retry></ForEach>'))
    rack, flasks, for_each = tree.children
    shake = for_each.children[0].children[0]
    assert rack.arguments == {'key': 'rack', 'type': 'box', 'color': 'blue'}
    assert for_each.arguments == {'source_key': 'flasks', 'target_key': 'flask'}
    assert for_each.children[0].arguments == {'num_failures': 2}
    assert shake.name == 'ShakeFlask' and shake.arguments == {'obj': '{flask}', 'times': 3}
    assert isinstance(shake, bt_nodes.Shake) and shake.times == 3


def test_the_judge_outline_reads_the_built_tree():
    _, tree = run_checks(document(RACK, FLASKS, LOOP))
    assert loop.outline_for_judge(tree) == (
        'Sequence [Root]\n'
        '    FindOne(key="rack", type="box", color="blue") [FindRack]\n'
        '    FindAll(key="flasks", type="measuring cylinder") [FindFlasks]\n'
        '    ForEach(source_key="flasks", target_key="flask") [ForEachFlask]\n'
        '        Place(obj="{flask}", location="{rack}") [PlaceFlask]')


def test_booleans_are_true_or_false_in_any_case():
    checks, tree = run_checks(document(
        '<FindAll name="FindTubes" key="tubes" type="test tube" closed="False" marked="true"/>',
        '<ForEach name="ForEachTube" source_key="tubes" target_key="tube">'
        '<HasProperty name="TubeHoldsLiquid" obj="{tube}" property="holds_liquid" '
        'value="True"/></ForEach>'))
    assert failures(checks) == []
    assert tree.children[0].arguments['closed'] is False
    assert tree.children[1].children[0].arguments['value'] is True


def test_finds_may_stand_after_an_action_and_inside_a_loop():
    checks, _ = run_checks(document(
        FLASKS,
        '<ForEach name="ForEachFlask" source_key="flasks" target_key="flask">'
        '<Sequence name="HandleFlask" memory="true">'
        '<FindOne name="FindRackInLoop" key="rack" type="box"/>'
        '<Place name="PlaceFlask" obj="{flask}" location="{rack}"/>'
        '</Sequence></ForEach>',
        '<FindOne name="FindCube" key="cube" type="cube"/>',
        '<FindOne name="FindBowl" key="bowl" type="bowl"/>',
        '<Place name="PlaceCube" obj="{cube}" location="{bowl}"/>'))
    assert failures(checks) == []


def test_a_fenced_reply_is_extracted():
    reply = f'Here is the tree:\n```xml\n{document(RACK)}```\n'
    assert xml_tree.extract_xml(reply).startswith('<root')
    assert xml_tree.extract_xml(document(RACK)).startswith('<root')
    assert xml_tree.extract_xml('I would rather ask how many times.') is None


# --- Syntax ------------------------------------------------------------------------

def test_malformed_xml_names_its_line():
    checks, tree = run_checks(document('<FindAll name="FindA" key="a">'))
    assert failures(checks) == ['syntax.parse'] and tree is None
    # Line 4 opens a FindAll that is never closed; the parser notices at line 5.
    assert checks['syntax.parse'].line == 5
    assert 'line 5' in checks['syntax.parse'].message


@pytest.mark.parametrize('text, message', [
    (document(RACK).replace('main_tree_to_execute="MainTree"', ''), 'main_tree_to_execute'),
    (document(RACK).replace('ID="MainTree"', 'ID="Main"'), 'ID="MainTree"'),
    ('<root main_tree_to_execute="MainTree">' + RACK + '</root>', 'exactly one <BehaviorTree>'),
])
def test_the_frame_is_required(text, message):
    checks, _ = run_checks(text)
    assert 'syntax.document' in failures(checks)
    assert message in checks['syntax.document'].message


def test_stray_text_is_only_a_warning():
    checks, _ = run_checks(document(RACK, 'then place it'))
    assert failures(checks) == []
    assert not checks['syntax.text'].passed


# --- Structure -------------------------------------------------------------------

def test_the_root_must_be_the_root_sequence():
    text = document(RACK).replace('<Sequence name="Root" memory="true">',
                                  '<Selector name="Root" memory="true">')
    text = text.replace('    </Sequence>\n  </BehaviorTree>', '    </Selector>\n  </BehaviorTree>')
    checks, _ = run_checks(text)
    assert failures(checks) == ['structure.root_type']


@pytest.mark.parametrize('node, message', [
    ('<OneShot name="Once" policy="ON_COMPLETION">' + RACK + '</OneShot>', 'OneShot'),
    ('<Parallel name="Both">' + RACK + '</Parallel>', 'no Parallel'),
    ('<Pick name="PickCube" obj="{cube}"/>', 'Pick'),
])
def test_tags_outside_the_grammar_are_refused(node, message):
    checks, _ = run_checks(document(node))
    assert 'structure.allowed_nodes' in failures(checks)
    assert message in checks['structure.allowed_nodes'].message


def test_a_decorator_removed_from_the_config_is_refused(monkeypatch):
    monkeypatch.setattr(config, 'GRAMMAR_DECORATORS', ('ForEach', 'Inverter'))
    checks, _ = run_checks(document(f'<Retry name="RetryFind" num_failures="2">{RACK}</Retry>'))
    assert failures(checks) == ['structure.allowed_nodes']


def test_memory_false_fails_and_missing_memory_warns():
    off = document(f'<Sequence name="Inner" memory="false">{RACK}</Sequence>')
    checks, _ = run_checks(off)
    assert failures(checks) == ['structure.memory']

    unwritten = document(f'<Sequence name="Inner">{RACK}</Sequence>')
    checks, _ = run_checks(unwritten)
    assert failures(checks) == [] and not checks['structure.memory_written'].passed


@pytest.mark.parametrize('node', [
    '<Inverter name="NotAny"><FindAll name="FindA" key="a"/><FindAll name="FindB" key="b"/></Inverter>',
    '<Sequence name="Empty" memory="true"></Sequence>',
    f'<FindOne name="FindBox" key="box" type="box">{FLASKS}</FindOne>',
])
def test_children_are_counted(node):
    checks, _ = run_checks(document(node))
    assert 'structure.children' in failures(checks)


def test_duplicate_names_are_refused_even_under_different_parents():
    checks, _ = run_checks(document(
        '<Sequence name="First" memory="true"><FindAll name="FindA" key="a"/></Sequence>',
        '<Sequence name="Second" memory="true"><FindAll name="FindA" key="b"/></Sequence>'))
    assert failures(checks) == ['structure.unique_names']


def test_an_inverter_around_a_condition_passes_and_around_an_action_fails():
    has = '<HasProperty name="RackIsBlue" obj="{rack}" property="color" value="blue"/>'
    checks, _ = run_checks(document(RACK, f'<Inverter name="RackIsNotBlue">{has}</Inverter>'))
    assert failures(checks) == []

    place = '<Place name="PlaceCube" obj="{cube}" location="{rack}"/>'
    checks, _ = run_checks(document(RACK, '<FindOne name="FindCube" key="cube" type="cube"/>',
                                    f'<Inverter name="DoNotPlace">{place}</Inverter>'))
    assert failures(checks) == ['structure.inverter']


# --- Arguments ---------------------------------------------------------------------

@pytest.mark.parametrize('node, message', [
    ('<Place name="PlaceRack" obj="{rack}"/>', 'missing location'),
    ('<Place name="PlaceRack" obj="{rack}" location="{rack}" speed="2"/>', 'does not take speed'),
    ('<FindOne name="FindBlock" key="block" shape="cube"/>', 'properties: type'),
])
def test_every_node_gets_exactly_its_arguments(node, message):
    checks, _ = run_checks(document(RACK, node))
    assert failures(checks) == ['arguments.signatures']
    assert message in checks['arguments.signatures'].message


@pytest.mark.parametrize('node', [
    '<Shake name="ShakeRack" obj="{rack}" times="two"/>',
    '<Shake name="ShakeRack" obj="{rack}" times="0"/>',
    f'<Retry name="RetryFind" num_failures="-1">{FLASKS}</Retry>',
    f'<Timeout name="GiveUp" duration="soon">{FLASKS}</Timeout>',
])
def test_counts_are_whole_numbers(node):
    checks, _ = run_checks(document(RACK, node))
    assert failures(checks) == ['arguments.counts']


@pytest.mark.parametrize('name', ['Root.FindBox', '', 'Find Box'])
def test_names_are_letters_and_digits(name):
    checks, _ = run_checks(document(f'<FindOne name="{name}" key="box" type="box"/>'))
    assert 'arguments.names' in failures(checks)


# --- Objects -----------------------------------------------------------------------

@pytest.mark.parametrize('arguments, message', [
    ('type="bolt"', 'not a type the robot perceives'),
    ('color="Blue"', 'lowercase colour name'),
    ('graspable="yes"', 'must be True or False'),
    ('type="box" position="middle"', 'position='),
    ('type="box" nth="0"', 'whole number of 1 or more'),
    ('type="box" nth="2nd"', 'whole number of 1 or more'),
])
def test_a_find_node_with_a_value_the_robot_does_not_have_is_refused(arguments, message):
    checks, _ = run_checks(document(f'<FindOne name="FindBox" key="box" {arguments}/>'))
    assert failures(checks) == ['objects.properties']
    assert message in checks['objects.properties'].message


@pytest.mark.parametrize('arguments', ['count="-1"', 'count="three"',
                                       'count="2" comparison="more than"'])
def test_has_count_values_are_checked(arguments):
    checks, _ = run_checks(document(FLASKS, f'<HasCount name="CountFlasks" key="flasks" {arguments}/>'))
    assert failures(checks) == ['objects.properties']


@pytest.mark.parametrize('node, message', [
    ('<Place name="PlaceFlask" obj="@flask" location="{rack}"/>', 'curly braces'),
    ('<Place name="PlaceFlask" obj="flask" location="{rack}"/>', 'not a reference'),
    ('<Place name="PlaceFlask" obj="{nothing}" location="{rack}"/>', 'no node stores'),
    ('<Place name="PlaceFlasks" obj="{flasks}" location="{rack}"/>', 'holds a list'),
    ('<HasCount name="CountRack" key="rack" count="1"/>', 'holds one object'),
    ('<HasCount name="CountFlasks" key="{flasks}" count="1"/>', 'plain name'),
    ('<Place name="PlaceFlask" obj="{flask}" location="{rack}"/>', 'only be used inside'),
])
def test_references_are_checked(node, message):
    checks, _ = run_checks(document(RACK, FLASKS, LOOP.replace('PlaceFlask', 'PlaceInLoop'),
                                    node))
    assert failures(checks) == ['objects.references']
    assert message in checks['objects.references'].message


def test_a_key_stored_after_it_is_used_is_refused():
    checks, _ = run_checks(document('<Place name="PlaceCube" obj="{cube}" location="{rack}"/>',
                                    RACK, '<FindOne name="FindCube" key="cube" type="cube"/>'))
    assert failures(checks) == ['objects.references']
    assert 'after this node runs' in checks['objects.references'].message


@pytest.mark.parametrize('nodes, message', [
    (('<FindOne name="FindRack" key="{rack}" type="box"/>',), 'without braces'),
    ((RACK, '<FindOne name="FindRackAgain" key="rack" type="box"/>'), 'already stored'),
])
def test_keys_are_plain_names_stored_once(nodes, message):
    checks, _ = run_checks(document(*nodes))
    assert 'objects.keys' in failures(checks)
    assert message in checks['objects.keys'].message


def test_braces_outside_a_reference_are_refused():
    checks, _ = run_checks(document('<FindOne name="FindBox" key="box" color="{red}"/>'))
    assert 'objects.references' in failures(checks)


# --- Build ---------------------------------------------------------------------------

def test_a_tree_with_errors_is_not_built():
    checks, tree = run_checks(document('<Place name="PlaceCube" obj="{cube}" location="{rack}"/>'))
    assert tree is None and checks['build.parse'].severity == 'warning'


def test_the_node_classes_take_the_properties_the_config_lists():
    import inspect
    taken = inspect.signature(bt_nodes._Find.__init__).parameters
    for prop in xml_tree.perception_properties():
        assert prop in taken, f'bt_nodes._Find does not take {prop}'


def test_the_registry_holds_exactly_the_leaves_of_the_grammar():
    assert set(bt_nodes.REGISTRY) == set(xml_tree.LEAVES)


def test_a_tree_the_check_built_has_no_world_and_cannot_be_ticked():
    # The check only builds. To run a tree, build it with bt_nodes.registry(world).
    import py_trees
    _, tree = run_checks(GLASS_BY_COUNT)
    behaviour_tree = py_trees.trees.BehaviourTree(tree)
    with pytest.raises(RuntimeError, match='built without a world'):
        behaviour_tree.tick()
