"""The nodes an XML behavior tree is built from, as py_trees ports nodes.

Goes to ``modules/bt_nodes.py``.

The py_trees XML parser (``py_trees.parsers.behaviour_tree_xml``) only builds leaves that
are ``PortsMixin`` classes, so the four actions and the four find/check nodes are defined
here that way. The composites (``Sequence``, ``Selector``) and the decorators
(``ForEach``, ``Inverter``, ``Retry``, ...) stay the built-in py_trees classes: the parser
builds those from their tag names itself.

How an XML attribute reaches a node:
- An object argument (``obj="{cube}"``) is an input port. The parser wires it to the
  blackboard key ``/cube``.
- Every other attribute (``key="cube"``, ``times="2"``, ``type="box"``) is a constructor
  argument. The parser converts it to the type annotated below.

A node acts on the ``world`` its class carries (modules/world.py). To run a tree, build it
with ``registry(world)``. ``REGISTRY`` has no world: the syntax check builds with it and
never ticks. The constructors and ports must stay as they are, because the XML is written
against them.
"""

import py_trees
from py_trees.ports import BehaviourWithPorts, PortInformation

import config

SUCCESS = py_trees.common.Status.SUCCESS
FAILURE = py_trees.common.Status.FAILURE

# An object found on the table. ``object`` accepts whatever the executor stores; tighten
# it to the executor's own object class once that exists.
OBJECT = PortInformation(data_type=object, required=True)


class _Node(BehaviourWithPorts, register=False):
    """A leaf that remembers its arguments, so the graph and the judge outline can show them."""

    INPUT_PORTS = {}
    OUTPUT_PORTS = {}
    world = None             # set by registry(world)

    def __init__(self, name: str, **kwargs):
        super().__init__(name=name, **kwargs)
        self.arguments = {}

    def update(self):
        if self.world is None:
            raise RuntimeError(f'{self.name} was built without a world; '
                               f'build the tree with bt_nodes.registry(world)')
        return self.act()

    def act(self):
        """What the node does on its world; sets feedback_message and returns a status."""
        raise NotImplementedError

    def finish(self, ok, feedback):
        self.feedback_message = feedback
        return SUCCESS if ok else FAILURE


# --- The four actions ---------------------------------------------------------

class _Action(_Node, register=False):
    action = 'Action'        # how modules/graph.py tells actions from other leaves

    def report(self, outcome, done):
        """The world's outcome as a status; done is the sentence for a plain success.

        FAILURE when the action did not happen, or when it happened with a fault and
        config.MOCK_SPILL_FAILS_ACTION is True; SUCCESS otherwise.
        """
        failed = not outcome.action_happened or (
            bool(outcome.fault) and config.MOCK_SPILL_FAILS_ACTION)
        return self.finish(not failed, outcome.reason or done)


class Place(_Action):
    action = 'Place'
    INPUT_PORTS = {'obj': OBJECT, 'location': OBJECT}

    def act(self):
        obj, location = self.get_input('obj'), self.get_input('location')
        return self.report(self.world.place(obj, location), f'placed {obj} in {location}')


class Pour(_Action):
    action = 'Pour'
    INPUT_PORTS = {'source': OBJECT, 'target': OBJECT}

    def act(self):
        source, target = self.get_input('source'), self.get_input('target')
        return self.report(self.world.pour(source, target), f'poured {source} into {target}')


class Shake(_Action):
    action = 'Shake'
    INPUT_PORTS = {'obj': OBJECT}

    def __init__(self, name: str, times: int, **kwargs):
        super().__init__(name=name, **kwargs)
        self.times = times

    def act(self):
        obj = self.get_input('obj')
        return self.report(self.world.shake(obj, self.times),
                           f'shook {obj} {self.times} time(s)')


class Close(_Action):
    action = 'Close'
    INPUT_PORTS = {'obj': OBJECT, 'closing_obj': OBJECT}

    def act(self):
        obj, closing_obj = self.get_input('obj'), self.get_input('closing_obj')
        return self.report(self.world.close(obj, closing_obj),
                           f'closed {obj} with {closing_obj}')


# --- Finding and checking objects ----------------------------------------------

class _Perception(_Node, register=False):
    perception = True        # how modules/graph.py draws find/check nodes


class _Find(_Perception, register=False):
    """FindOne and FindAll. The property arguments must match config.PERCEPTION_*."""

    def __init__(self, name: str, key: str, type: str | None = None,
                 color: str | None = None, liquid_color: str | None = None,
                 graspable: bool | None = None, holds_liquid: bool | None = None,
                 closed: bool | None = None, marked: bool | None = None,
                 position: str | None = None, **kwargs):
        super().__init__(name=name, **kwargs)
        self.key = key
        self.properties = {prop: value for prop, value in {
            'type': type, 'color': color, 'liquid_color': liquid_color,
            'graspable': graspable, 'holds_liquid': holds_liquid, 'closed': closed,
            'marked': marked}.items() if value is not None}
        self.position = position

    def found(self):
        """The objects this node describes. The client is made here and not in __init__,
        so the syntax check's builds register nothing."""
        if not hasattr(self, '_store'):
            self._store = py_trees.blackboard.Client(name=self.name)
            self._store.register_key(key=self.key, access=py_trees.common.Access.WRITE)
        return self.world.perceive(self.properties, self.position)

    def described(self):
        return ', '.join(f'{prop}={value!r}' for prop, value in self.properties.items()) \
            or 'any properties'


class FindOne(_Find):
    def __init__(self, name: str, key: str, nth: int = 1, **kwargs):
        super().__init__(name=name, key=key, **kwargs)
        self.nth = nth

    def act(self):
        found = self.found()
        if len(found) < self.nth:
            return self.finish(False, f'found only {len(found)} object(s) with '
                                      f'{self.described()}; wanted number {self.nth}')
        self._store.set(self.key, found[self.nth - 1])
        return self.finish(True, f'stored {found[self.nth - 1]} under {self.key}')


class FindAll(_Find):
    def __init__(self, name: str, key: str, limit: int | None = None, **kwargs):
        super().__init__(name=name, key=key, **kwargs)
        self.limit = limit

    def act(self):
        found = self.found()
        kept = found[:self.limit] if self.limit else found
        self._store.set(self.key, kept)
        return self.finish(True, f'stored {len(kept)} object(s) under {self.key}: {kept}')


class HasProperty(_Perception):
    INPUT_PORTS = {'obj': OBJECT}

    def __init__(self, name: str, property: str, value: str, **kwargs):
        super().__init__(name=name, **kwargs)
        self.property = property
        self.value = value       # as written; act() converts True/False itself

    def act(self):
        obj = self.get_input('obj')
        value = self.value
        if self.property in config.PERCEPTION_BOOLEAN_PROPERTIES:
            value = str(value).lower() == 'true'
        return self.finish(self.world.matches(obj, {self.property: value}),
                           f'{obj} has {self.property} = {getattr(obj, self.property)!r}; '
                           f'wanted {value!r}')


class HasCount(_Perception):
    def __init__(self, name: str, key: str, count: int, comparison: str = 'exactly',
                 **kwargs):
        super().__init__(name=name, **kwargs)
        self.key = key
        self.count = count
        self.comparison = comparison

    def act(self):
        if not hasattr(self, '_list'):
            self._list = py_trees.blackboard.Client(name=self.name)
            self._list.register_key(key=self.key, access=py_trees.common.Access.READ)
        number = len(self._list.get(self.key))
        ok = {'exactly': number == self.count, 'at least': number >= self.count,
              'at most': number <= self.count}[self.comparison]
        return self.finish(ok, f'{self.key} has {number} object(s); '
                               f'wanted {self.comparison} {self.count}')


# The only leaf tags the parser may build. Passing this dict to the parser, instead of
# its default "auto" registry, keeps it from building any other ports class.
REGISTRY = {cls.__name__: cls for cls in (Place, Pour, Shake, Close,
                                          FindOne, FindAll, HasProperty, HasCount)}


def registry(world):
    """The tag → class map for running a tree on this world.

    Each node class gets a subclass that carries the world as a class attribute. It must
    be a class and not functools.partial: py_trees converts XML text to the annotated
    types (marked="False" → False, limit="2" → 2) by reading the class and its parents'
    __init__, and a partial hides the parents, so the find properties would stay strings.
    """
    return {tag: type(tag, (cls,), {'world': world, '__module__': cls.__module__},
                      register=False)
            for tag, cls in REGISTRY.items()}
