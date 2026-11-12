"""Running trees on the real scenes, and the trace of a run.

    ../contextual-asr/venv/bin/python -m pytest tests -q
"""

import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from modules.executor import execute, format_trace  # noqa: E402
from modules.mock_world import MockWorld  # noqa: E402
from modules.scene import load_scene  # noqa: E402

SCENE6_TREE = """\
<root main_tree_to_execute="MainTree">
  <BehaviorTree ID="MainTree">
    <Sequence name="Root" memory="true">
      <FindAll name="FindEveryObject" key="objects"/>
      <ForEach name="ForEachObject" source_key="objects" target_key="object">
        <Selector name="ChooseObjectDestination" memory="true">
          <Sequence name="PlaceMarkedObjectInPalette" memory="true">
            <HasProperty name="ObjectIsMarked" obj="{object}" property="marked" value="True"/>
            <FindOne name="FindPalette" key="palette" type="palette"/>
            <Place name="PlaceMarkedObject" obj="{object}" location="{palette}"/>
          </Sequence>
          <Sequence name="PlaceUnmarkedObjectInBlueBox" memory="true">
            <HasProperty name="ObjectIsUnmarked" obj="{object}" property="marked" value="False"/>
            <FindOne name="FindBlueBox" key="bluebox" type="box" color="blue"/>
            <Place name="PlaceUnmarkedObject" obj="{object}" location="{bluebox}"/>
          </Sequence>
        </Selector>
      </ForEach>
    </Sequence>
  </BehaviorTree>
</root>
"""
SCENE6_GRASPABLE = SCENE6_TREE.replace('key="objects"/>', 'key="objects" graspable="True"/>')

PLACED = {'white_marked_package_1': 'brown_palette', 'white_marked_package_2': 'brown_palette',
          'white_package_1': 'blue_box', 'white_package_2': 'blue_box',
          'white_package_3': 'blue_box'}


def document(*nodes):
    body = '\n'.join(f'      {node}' for node in nodes)
    return ('<root main_tree_to_execute="MainTree">\n'
            '  <BehaviorTree ID="MainTree">\n'
            '    <Sequence name="Root" memory="true">\n'
            f'{body}\n'
            '    </Sequence>\n'
            '  </BehaviorTree>\n'
            '</root>\n')


def run(scene, tree, **kwargs):
    return execute(tree, MockWorld.from_scene(load_scene(scene)), **kwargs)


def table(result):
    return {obj['id']: obj for obj in result['final_table']['objects']}


def events(result):
    return [event for entry in result['trace'] for event in entry['events']]


def placements(result):
    return {id: obj['on'] for id, obj in table(result).items() if obj['on']}


def close_and_shake(number, close=True):
    nodes = [f'<FindOne name="FindTube{number}" key="tube{number}" type="test tube" nth="{number}"/>']
    if close:
        nodes += [f'<FindOne name="FindCap{number}" key="cap{number}" type="test tube cap" nth="{number}"/>',
                  f'<Close name="Close{number}" obj="{{tube{number}}}" closing_obj="{{cap{number}}}"/>']
    nodes.append(f'<Shake name="Shake{number}" obj="{{tube{number}}}" times="2"/>')
    return nodes


# --- 1 and 2: scene6 ---------------------------------------------------------------

def test_scene6_without_graspable_fails_on_the_palette():
    result = run('scene6', SCENE6_TREE)
    assert result['status'] == 'FAILURE' and result['stopped'] == 'finished'
    assert placements(result) == PLACED
    done = events(result)
    assert [event['action_happened'] for event in done] == [True] * 5 + [False]
    last = done[-1]
    assert last['arguments'] == {'obj': 'brown_palette', 'location': 'blue_box'}
    assert 'brown_palette' in last['reason']


def test_scene6_scan_order():
    done = events(run('scene6', SCENE6_TREE))
    assert [event['arguments']['obj'] for event in done] == [
        'white_package_1', 'white_marked_package_1', 'white_package_2',
        'white_marked_package_2', 'white_package_3', 'brown_palette']


def test_scene6_with_graspable_succeeds():
    result = run('scene6', SCENE6_GRASPABLE)
    assert result['status'] == 'SUCCESS' and result['stopped'] == 'finished'
    assert placements(result) == PLACED
    assert all(event['action_happened'] for event in events(result))


# --- 3: scene8 -----------------------------------------------------------------------

def test_scene8_close_then_shake_has_no_faults():
    nodes = [node for number in (1, 2, 3) for node in close_and_shake(number)]
    result = run('scene8', document(*nodes))
    assert result['status'] == 'SUCCESS'
    assert result['final_table']['faults'] == []
    tubes = table(result)
    for number in (1, 2, 3):
        tube = tubes[f'transparent_test_tube_{number}']
        assert tube['closed_by'] == f'yellow_test_tube_cap_{number}' and not tube['spilled']


def test_scene8_shake_without_close_spills():
    result = run('scene8', document(*close_and_shake(1, close=False)))
    assert result['status'] == 'SUCCESS'
    assert [fault['fault'] for fault in result['final_table']['faults']] == ['spill']
    assert table(result)['transparent_test_tube_1']['spilled']


# --- 4: scene2_1 ---------------------------------------------------------------------

FIND_BLACK_AND_BOWL = ('<FindOne name="FindBlack" key="black" liquid_color="black"/>',
                       '<FindOne name="FindBowl" key="bowl" type="bowl"/>')


def test_scene2_pour_into_the_bowl():
    result = run('scene2_1', document(*FIND_BLACK_AND_BOWL,
                                      '<Pour name="PourBlack" source="{black}" target="{bowl}"/>'))
    assert result['status'] == 'SUCCESS'
    objects = table(result)
    assert objects['yellow_bowl']['holds_liquid'] and objects['yellow_bowl']['liquid_color'] == 'black'
    cylinder = objects['transparent_measuring_cylinder_1']
    assert not cylinder['holds_liquid'] and cylinder['liquid_color'] == ''


def test_scene2_pouring_again_fails():
    result = run('scene2_1', document(*FIND_BLACK_AND_BOWL,
                                      '<Pour name="PourBlack" source="{black}" target="{bowl}"/>',
                                      '<Pour name="PourAgain" source="{black}" target="{bowl}"/>'))
    assert result['status'] == 'FAILURE'
    assert 'holds no liquid' in events(result)[-1]['reason']


# --- 5 and 6: the loose colour rule and a HasCount choice ------------------------------

def test_scene8_loose_liquid_colour_finds_the_tubes():
    result = run('scene8', document('<FindAll name="FindRed" key="red" liquid_color="red"/>'))
    assert result['status'] == 'SUCCESS'
    assert result['trace'][-1]['blackboard']['/red'] == [
        f'transparent_test_tube_{number}' for number in (1, 2, 3)]


def has_count_tree(count):
    return document(
        '<FindAll name="FindMarked" key="marked" type="package" marked="True"/>',
        '<Selector name="ChooseByCount" memory="true">'
        '<Sequence name="WhenTheCountIsRight" memory="true">'
        f'<HasCount name="CountMarked" key="marked" count="{count}"/>'
        '<FindOne name="FindPalette" key="palette" type="palette"/>'
        '<ForEach name="ForEachMarked" source_key="marked" target_key="package">'
        '<Place name="PlaceMarked" obj="{package}" location="{palette}"/>'
        '</ForEach></Sequence>'
        '<FindAll name="OtherwiseNothing" key="nothing" type="cup"/>'
        '</Selector>')


def test_scene6_has_count_choice():
    result = run('scene6', has_count_tree(2))
    assert result['status'] == 'SUCCESS'
    assert placements(result) == {'white_marked_package_1': 'brown_palette',
                                  'white_marked_package_2': 'brown_palette'}


def test_scene6_has_count_choice_not_taken():
    result = run('scene6', has_count_tree(3))
    assert result['status'] == 'SUCCESS' and placements(result) == {}


# --- 7: the trace ------------------------------------------------------------------------

def test_the_trace_goes_through_json():
    result = run('scene6', SCENE6_TREE)
    assert json.loads(json.dumps(result))['status'] == 'FAILURE'


def test_the_trace_shows_the_blackboard():
    trace = run('scene6', SCENE6_TREE)['trace']
    assert {'key': '/objects', 'action': 'WRITE', 'by': 'FindEveryObject',
            'value': ['white_package_1', 'white_marked_package_1', 'white_package_2',
                      'white_marked_package_2', 'white_package_3', 'brown_palette', 'blue_box']
            } in trace[0]['activity']
    writes = [[item['value'] for item in entry['activity']
               if item['key'] == '/object' and item['action'] == 'WRITE' and
               item['by'] == 'ForEachObject'] for entry in trace]
    assert 'white_package_1' in writes[0]
    assert 'white_package_2' in writes[1]
    assert trace[0]['blackboard']['/objects'][0] == 'white_package_1'
    assert isinstance(trace[0]['blackboard']['/object'], str)


def test_the_trace_has_no_consecutive_duplicates():
    for entry in run('scene6', SCENE6_TREE)['trace']:
        for before, after in zip(entry['activity'], entry['activity'][1:]):
            assert before != after


def test_every_name_in_the_trace_is_a_short_xml_name():
    names = set(re.findall(r' name="([^"]+)"', SCENE6_TREE))
    trace = run('scene6', SCENE6_TREE)['trace']
    for entry in trace:
        assert {node['node'] for node in entry['visited']} <= names
        assert {item['by'] for item in entry['activity']} <= names


def test_visited_holds_the_nodes_of_the_tick_with_their_status_and_feedback():
    first = run('scene6', SCENE6_TREE)['trace'][0]['visited']
    by_name = {node['node']: node for node in first}
    assert by_name['FindEveryObject']['type'] == 'FindAll'
    assert by_name['FindEveryObject']['status'] == 'SUCCESS'
    assert by_name['ObjectIsMarked']['status'] == 'FAILURE'
    assert by_name['PlaceUnmarkedObject']['feedback'] == 'placed white_package_1 in blue_box'
    names = [node['node'] for node in first]
    assert names.index('ObjectIsMarked') < names.index('ObjectIsUnmarked')


def test_format_trace_shows_the_run():
    text = format_trace(run('scene6', SCENE6_TREE))
    assert '--- tick 1 ' in text
    assert 'WRITE /objects = ' in text
    assert 'Status: FAILURE' in text
    assert 'white_package_1: on blue_box' in text
    assert 'brown_palette is fixed' in text
    assert 'brown_palette:' not in text.split('Where every graspable object ended up:')[1]


def test_format_trace_shows_faults():
    text = format_trace(run('scene8', document(*close_and_shake(1, close=False))))
    assert 'spill: transparent_test_tube_1 was shaken while open and spilled' in text


# --- 8: the blackboard is reset -----------------------------------------------------------

def test_every_run_starts_with_an_empty_blackboard():
    run('scene6', SCENE6_TREE)
    second = run('scene6', document('<FindOne name="FindBox" key="box" type="box"/>'))
    assert list(second['trace'][0]['blackboard']) == ['/box']
    assert [item['key'] for item in second['trace'][0]['activity']] == ['/box']


def test_the_same_tree_twice_gives_the_same_result():
    assert run('scene6', SCENE6_TREE) == run('scene6', SCENE6_TREE)


# --- 9 and 10: stopping ---------------------------------------------------------------------

LOOPS_FOREVER = document(
    '<FindOne name="FindBox" key="box" type="box"/>',
    '<Retry name="RetryForever" num_failures="100000">'
    '<Place name="PlaceTheBox" obj="{box}" location="{box}"/>'
    '</Retry>')


def test_a_tree_that_never_finishes_stops_at_the_limit():
    result = run('scene6', LOOPS_FOREVER)
    assert result['stopped'] == 'max_ticks' and result['status'] == 'RUNNING'
    assert result['ticks'] == config.EXECUTION_MAX_TICKS


def test_max_ticks_can_be_given():
    assert run('scene6', LOOPS_FOREVER, max_ticks=5)['ticks'] == 5


def test_a_tree_that_fails_the_check_is_not_ticked():
    bad = document('<Place name="PlaceNothing" obj="{nothing}" location="{nowhere}"/>')
    world = MockWorld.from_scene(load_scene('scene6'))
    before = world.snapshot()
    result = execute(bad, world)
    assert result['status'] == 'INVALID' and result['stopped'] == 'invalid'
    assert result['ticks'] == 0 and result['trace'] == []
    assert any('no node stores "nothing"' in message for message in result['check_errors'])
    assert result['final_table'] == before
    assert world.take_events() == []


def test_xml_that_does_not_parse_is_invalid():
    result = run('scene6', '<root><unclosed></root>')
    assert result['status'] == 'INVALID' and result['check_errors']


def test_a_node_that_raises_stops_the_run_with_the_message(monkeypatch):
    world = MockWorld.from_scene(load_scene('scene6'))

    def broken(*_args):
        raise ValueError('the arm is stuck')
    monkeypatch.setattr(world, 'perceive', broken)
    result = execute(SCENE6_TREE, world)
    assert result['status'] == 'ERROR' and result['stopped'] == 'error'
    assert 'the arm is stuck' in result['error']
    assert result['ticks'] == 1
    assert json.dumps(result)
    assert 'the arm is stuck' in format_trace(result)
