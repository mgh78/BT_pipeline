"""The mock world: perception, the physical rules, and every scene.

    ../contextual-asr/venv/bin/python -m pytest tests -q
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from modules.mock_world import MockWorld  # noqa: E402
from modules.scene import load_scene  # noqa: E402
from modules.world import WorldObject  # noqa: E402


def thing(id, type, x, y, **fields):
    fields.setdefault('color', 'white')
    fields.setdefault('graspable', type not in config.SUPPORT_OBJECTS)
    return WorldObject(id=id, type=type, position={'x': x, 'y': y, 'z': 0.0}, **fields)


def packages():
    return MockWorld([
        thing('palette', 'palette', 0.50, 0.30, color='brown'),
        thing('package_a', 'package', 0.40, -0.10),
        thing('package_b', 'package', 0.60, -0.10, marked=True),
        thing('package_c', 'package', 0.30, 0.20),
        thing('blue_box', 'box', 0.70, 0.00, color='blue'),
        thing('red_cube', 'cube', 0.35, 0.05, color='red'),
    ])


def lab():
    return MockWorld([
        thing('bowl', 'bowl', 0.60, 0.00, color='yellow'),
        thing('red_tube', 'test tube', 0.40, 0.10, color='transparent',
              holds_liquid=True, liquid_color='red'),
        thing('black_tube', 'test tube', 0.40, 0.20, color='transparent',
              holds_liquid=True, liquid_color='black'),
        thing('empty_tube', 'test tube', 0.40, 0.30, color='transparent'),
        thing('cap_1', 'test tube cap', 0.50, 0.40, color='yellow'),
        thing('cap_2', 'test tube cap', 0.55, 0.40, color='yellow'),
        thing('cube', 'cube', 0.30, 0.00, color='red'),
    ])


def get(world, object_id):
    return next(o for o in world.objects if o.id == object_id)


def ids(objects):
    return [o.id for o in objects]


# --- perceive ---------------------------------------------------------------------

def test_perceive_filters_by_every_property():
    world = packages()
    assert ids(world.perceive({'type': 'package', 'marked': False})) == ['package_a', 'package_c']
    assert ids(world.perceive({'type': 'box', 'color': 'blue'})) == ['blue_box']
    assert world.perceive({'type': 'box', 'color': 'red'}) == []
    assert world.perceive({'no_such_property': 1}) == []


def test_empty_properties_match_everything():
    world = packages()
    assert len(world.perceive({})) == len(world.objects)


def test_scan_order_and_positions():
    world = packages()
    found = lambda position=None: ids(world.perceive({'type': 'package'}, position))
    assert found() == ['package_a', 'package_b', 'package_c']          # y, then x
    assert found('leftmost')[-1] == 'package_c'
    assert found('leftmost')[:2] == ['package_a', 'package_b']
    assert found('rightmost')[0] == 'package_c'
    assert found('nearest') == ['package_c', 'package_a', 'package_b']
    assert found('farthest') == ['package_b', 'package_a', 'package_c']


def test_marked_splits_the_objects():
    world = packages()
    assert ids(world.perceive({'marked': True})) == ['package_b']
    assert 'package_b' not in ids(world.perceive({'marked': False}))
    assert len(world.perceive({'marked': False})) == len(world.objects) - 1


# --- place ------------------------------------------------------------------------

def test_place_into_a_box():
    world = packages()
    outcome = world.place(get(world, 'red_cube'), get(world, 'blue_box'))
    assert outcome.ok and not outcome.fault
    cube = get(world, 'red_cube')
    assert cube.on == 'blue_box' and cube.position == get(world, 'blue_box').position


@pytest.mark.parametrize('obj, location, named', [
    ('blue_box', 'palette', 'blue_box'),
    ('red_cube', 'package_a', 'package_a'),
    ('red_cube', 'red_cube', 'red_cube'),
])
def test_place_refusals(obj, location, named):
    world = packages()
    outcome = world.place(get(world, obj), get(world, location))
    assert not outcome.ok and named in outcome.reason


# --- pour -------------------------------------------------------------------------

def test_pour_into_a_bowl_and_into_a_tube():
    world = lab()
    assert world.pour(get(world, 'red_tube'), get(world, 'empty_tube')).ok
    tube = get(world, 'empty_tube')
    assert tube.holds_liquid and tube.liquid_color == 'red'
    source = get(world, 'red_tube')
    assert not source.holds_liquid and source.liquid_color == ''
    assert world.pour(get(world, 'black_tube'), get(world, 'bowl')).ok
    assert get(world, 'bowl').liquid_color == 'black'


def test_pour_different_colours_mixes():
    world = lab()
    assert world.pour(get(world, 'red_tube'), get(world, 'black_tube')).ok
    assert get(world, 'black_tube').liquid_color == 'mixed'


def test_pour_refusals():
    world = lab()
    outcome = world.pour(get(world, 'empty_tube'), get(world, 'bowl'))
    assert not outcome.ok and 'empty_tube' in outcome.reason
    assert world.close(get(world, 'red_tube'), get(world, 'cap_1')).ok
    outcome = world.pour(get(world, 'red_tube'), get(world, 'bowl'))
    assert not outcome.ok and 'red_tube' in outcome.reason
    outcome = world.pour(get(world, 'black_tube'), get(world, 'red_tube'))
    assert not outcome.ok and 'closed' in outcome.reason
    outcome = world.pour(get(world, 'black_tube'), get(world, 'cube'))
    assert not outcome.ok and 'cube' in outcome.reason


# --- shake ------------------------------------------------------------------------

def test_shaking_an_open_tube_spills(monkeypatch):
    monkeypatch.setattr(config, 'MOCK_SPILL_FAILS_ACTION', False)
    world = lab()
    outcome = world.shake(get(world, 'red_tube'), 2)
    assert outcome.ok and outcome.fault == 'spill' and 'red_tube' in outcome.reason
    assert get(world, 'red_tube').spilled
    assert world.snapshot()['faults'][0]['fault'] == 'spill'


def test_spill_can_fail_the_action(monkeypatch):
    monkeypatch.setattr(config, 'MOCK_SPILL_FAILS_ACTION', True)
    world = lab()
    outcome = world.shake(get(world, 'red_tube'), 2)
    assert not outcome.ok and outcome.fault == 'spill'


def test_shaking_a_closed_tube_is_fine():
    world = lab()
    world.close(get(world, 'red_tube'), get(world, 'cap_1'))
    outcome = world.shake(get(world, 'red_tube'), 3)
    assert outcome.ok and not outcome.fault and not get(world, 'red_tube').spilled
    assert world.snapshot()['faults'] == []


@pytest.mark.parametrize('times', [0, -1, 1.5, True])
def test_shake_needs_a_positive_whole_number(times):
    world = lab()
    assert not world.shake(get(world, 'cube'), times).ok


# --- close ------------------------------------------------------------------------

def test_close_with_a_matching_cap():
    world = lab()
    assert world.close(get(world, 'red_tube'), get(world, 'cap_1')).ok
    tube, cap = get(world, 'red_tube'), get(world, 'cap_1')
    assert tube.closed and tube.closed_by == 'cap_1' and cap.on == 'red_tube'


def test_close_refusals():
    world = lab()
    world.close(get(world, 'red_tube'), get(world, 'cap_1'))
    outcome = world.close(get(world, 'red_tube'), get(world, 'cap_2'))
    assert not outcome.ok and 'already closed' in outcome.reason
    outcome = world.close(get(world, 'black_tube'), get(world, 'cap_1'))
    assert not outcome.ok and 'cap_1' in outcome.reason
    outcome = world.close(get(world, 'black_tube'), get(world, 'cube'))
    assert not outcome.ok and 'cube is not a cap or lid' in outcome.reason


# --- state and events -------------------------------------------------------------

@pytest.mark.parametrize('action', [
    lambda w: w.place(get(w, 'bowl'), get(w, 'cube')),
    lambda w: w.pour(get(w, 'empty_tube'), get(w, 'bowl')),
    lambda w: w.shake(get(w, 'red_tube'), 0),
    lambda w: w.close(get(w, 'red_tube'), get(w, 'cube')),
])
def test_a_refused_action_changes_nothing(action):
    world = lab()
    before = world.snapshot()
    assert not action(world).ok
    assert world.snapshot() == before


def test_take_events_returns_each_action_once():
    world = lab()
    world.place(get(world, 'cube'), get(world, 'bowl'))
    world.shake(get(world, 'cube'), 0)
    events = world.take_events()
    assert [e['action'] for e in events] == ['Place', 'Shake']
    assert events[0] == {'action': 'Place', 'arguments': {'obj': 'cube', 'location': 'bowl'},
                         'ok': True, 'reason': '', 'fault': ''}
    assert not events[1]['ok'] and events[1]['arguments'] == {'obj': 'cube', 'times': 0}
    assert world.take_events() == []


# --- the real scenes --------------------------------------------------------------

@pytest.mark.parametrize('scene_number', config.SCENES)
def test_every_scene_builds(scene_number):
    scene = load_scene(scene_number)
    world = MockWorld.from_scene(scene)
    assert len(world.objects) == len(scene.objects)
    for obj in world.objects:
        assert obj.type in config.PERCEPTION_TYPES, obj.id
        assert not obj.closed and obj.on is None
    other = MockWorld.from_scene(scene)
    assert not any(a is b or a.position is b.position
                   for a in world.objects for b in other.objects)
    assert not any(a is b for a, b in zip(world.objects, scene.objects))


def test_scene_mapping():
    world = MockWorld.from_scene(load_scene('scene6'))
    marked = get(world, 'white_marked_package_1')
    assert marked.type == 'package' and marked.marked and marked.graspable
    assert not get(world, 'brown_palette').graspable
    tubes = MockWorld.from_scene(load_scene('scene8')).perceive({'type': 'test tube'})
    assert len(tubes) == 3
    assert all(t.holds_liquid and t.liquid_color == 'transparent red' for t in tubes)
