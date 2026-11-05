"""A world in plain Python: one of the pipeline's scenes, and the physical rules.

The rules follow prompts/generic_actions.txt and prompts/judge_physical_facts.txt. Each
action checks its rules in order and refuses with the first one that is broken, changing
nothing; otherwise it changes the table. Every call is recorded as an event.
"""

import copy

import config
from core import logging_setup
from modules.world import Outcome, World, WorldObject

log = logging_setup.get_logger('mock_world')

_MISSING = object()   # a property no object has never matches

# --- Rule tables ----------------------------------------------------------------

# Graspable objects that can be poured into. Every object that is not graspable is a
# container as well.
POURABLE_INTO = ('measuring cylinder', 'test tube', 'bottle', 'cup', 'bowl')

# Which cap or lid type closes which object types.
CAPS_FIT = {'test tube cap': ('test tube',)}

# How each position orders the objects (the scan order breaks ties).
ORDERS = {
    None: lambda o: (o.position['y'], o.position['x']),
    'leftmost': lambda o: o.position['y'],
    'rightmost': lambda o: -o.position['y'],
    'nearest': lambda o: o.position['x'],
    'farthest': lambda o: -o.position['x'],
}

# Each action's rules, checked in order: (test, reason when the test fails). A test gets
# the world and the action's arguments; the reason is formatted with the arguments.
PLACE_RULES = [
    (lambda w, obj, location: obj.graspable,
     '{obj} is fixed and cannot be grasped'),
    (lambda w, obj, location: not location.graspable,
     '{location} is not a place to put things'),
    (lambda w, obj, location: obj.id != location.id,
     '{obj} cannot be placed on itself'),
]

POUR_RULES = [
    (lambda w, source, target: source.graspable,
     '{source} is fixed and cannot be grasped'),
    (lambda w, source, target: source.holds_liquid,
     '{source} holds no liquid'),
    (lambda w, source, target: not source.closed,
     '{source} is closed and cannot be poured from'),
    (lambda w, source, target: not target.graspable or target.type in POURABLE_INTO,
     '{target} is not a container'),
    (lambda w, source, target: not target.closed,
     '{target} is closed; nothing can be poured into a closed container'),
]

SHAKE_RULES = [
    (lambda w, obj, times: obj.graspable,
     '{obj} is fixed and cannot be grasped'),
    (lambda w, obj, times: isinstance(times, int) and not isinstance(times, bool) and times >= 1,
     '{obj} cannot be shaken {times} times; times must be a whole number of 1 or more'),
]

CLOSE_RULES = [
    (lambda w, obj, closing_obj: obj.type in CAPS_FIT.get(closing_obj.type, ()),
     '{closing_obj} is not a cap or lid that fits {obj}'),
    (lambda w, obj, closing_obj: not obj.closed,
     '{obj} is already closed'),
    (lambda w, obj, closing_obj: not any(o.closed_by == closing_obj.id for o in w.objects),
     '{closing_obj} already closes another container; one cap closes one container'),
]


def from_scene_object(scene_object):
    """The WorldObject of one SceneObject, mapped as the judge prompt describes."""
    words = scene_object.name.split()
    return WorldObject(
        id=scene_object.id,
        type=' '.join(word for word in words if word != 'marked'),
        color=scene_object.color.lower(),
        liquid_color=scene_object.liquid_color.lower() if scene_object.holds_liquid else '',
        graspable=not scene_object.is_location,
        holds_liquid=scene_object.holds_liquid,
        closed=False,
        marked='marked' in words,
        position=dict(scene_object.position),
    )


class MockWorld(World):
    """A list of WorldObjects that the actions change."""

    def __init__(self, objects):
        self.objects = copy.deepcopy(list(objects))
        self.faults = []
        self._events = []

    @classmethod
    def from_scene(cls, scene):
        objects = [from_scene_object(o) for o in scene.objects]
        for obj in objects:
            if obj.type not in config.PERCEPTION_TYPES:
                log.warning('%s: %s has the type %r, which the robot does not perceive',
                            scene.number, obj.id, obj.type)
        return cls(objects)

    # --- Perception -------------------------------------------------------------

    def perceive(self, properties, position=None):
        found = [o for o in self.objects
                 if all(getattr(o, name, _MISSING) == value for name, value in properties.items())]
        found.sort(key=ORDERS[None])
        return sorted(found, key=ORDERS[position])

    # --- Actions ----------------------------------------------------------------

    def place(self, obj, location):
        def effect(obj, location):
            obj.on = location.id
            obj.position = dict(location.position)
            return Outcome(ok=True)
        return self._act('Place', PLACE_RULES, effect, obj=obj, location=location)

    def pour(self, source, target):
        def effect(source, target):
            if target.holds_liquid and target.liquid_color != source.liquid_color:
                target.liquid_color = 'mixed'
            else:
                target.liquid_color = source.liquid_color
            target.holds_liquid = True
            source.holds_liquid = False
            source.liquid_color = ''
            return Outcome(ok=True)
        return self._act('Pour', POUR_RULES, effect, source=source, target=target)

    def shake(self, obj, times):
        def effect(obj, times):
            if not obj.holds_liquid or obj.closed:
                return Outcome(ok=True)
            obj.spilled = True
            return Outcome(ok=not config.MOCK_SPILL_FAILS_ACTION, fault='spill',
                           reason=f'{obj.id} was shaken while open and spilled')
        return self._act('Shake', SHAKE_RULES, effect, obj=obj, times=times)

    def close(self, obj, closing_obj):
        def effect(obj, closing_obj):
            obj.closed = True
            obj.closed_by = closing_obj.id
            closing_obj.on = obj.id
            return Outcome(ok=True)
        return self._act('Close', CLOSE_RULES, effect, obj=obj, closing_obj=closing_obj)

    def _act(self, action, rules, effect, **arguments):
        """Check the rules in order, then carry out the effect; record the event."""
        resolved = {}
        outcome = None
        for name, value in arguments.items():
            if isinstance(value, WorldObject):
                own = self._by_id(value.id)
                if own is None:
                    outcome = Outcome(ok=False, reason=f'{value.id} is not on the table')
                    break
                value = own
            resolved[name] = value
        if outcome is None:
            for test, reason in rules:
                if not test(self, **resolved):
                    outcome = Outcome(ok=False, reason=reason.format(**resolved))
                    break
        if outcome is None:
            outcome = effect(**resolved)
        if outcome.fault:
            self.faults.append({'action': action, 'fault': outcome.fault,
                                'reason': outcome.reason})
        self._events.append({
            'action': action,
            'arguments': {name: value.id if isinstance(value, WorldObject) else value
                          for name, value in arguments.items()},
            'ok': outcome.ok,
            'reason': outcome.reason,
            'fault': outcome.fault,
        })
        return outcome

    def _by_id(self, object_id):
        for obj in self.objects:
            if obj.id == object_id:
                return obj
        return None

    # --- State ------------------------------------------------------------------

    def snapshot(self):
        return {'objects': [o.as_dict() for o in self.objects],
                'faults': copy.deepcopy(self.faults)}

    def take_events(self):
        events, self._events = self._events, []
        return events
