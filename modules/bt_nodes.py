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

These are stand-ins: they build and record their arguments, and ``update()`` only
succeeds. The executor replaces the ``update()`` bodies with real perception and motion
later; the constructors and ports must stay as they are, because the XML is written
against them.
"""

import py_trees
from py_trees.ports import BehaviourWithPorts, PortInformation

SUCCESS = py_trees.common.Status.SUCCESS

# An object found on the table. ``object`` accepts whatever the executor stores; tighten
# it to the executor's own object class once that exists.
OBJECT = PortInformation(data_type=object, required=True)


class _Node(BehaviourWithPorts, register=False):
    """A leaf that remembers its arguments, so the graph and the judge outline can show them."""

    INPUT_PORTS = {}
    OUTPUT_PORTS = {}

    def __init__(self, name: str, **kwargs):
        super().__init__(name=name, **kwargs)
        self.arguments = {}

    def update(self):
        return SUCCESS


# --- The four actions ---------------------------------------------------------

class _Action(_Node, register=False):
    action = 'Action'        # how modules/graph.py tells actions from other leaves


class Place(_Action):
    action = 'Place'
    INPUT_PORTS = {'obj': OBJECT, 'location': OBJECT}


class Pour(_Action):
    action = 'Pour'
    INPUT_PORTS = {'source': OBJECT, 'target': OBJECT}


class Shake(_Action):
    action = 'Shake'
    INPUT_PORTS = {'obj': OBJECT}

    def __init__(self, name: str, times: int, **kwargs):
        super().__init__(name=name, **kwargs)
        self.times = times


class Close(_Action):
    action = 'Close'
    INPUT_PORTS = {'obj': OBJECT, 'closing_obj': OBJECT}


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


class FindOne(_Find):
    def __init__(self, name: str, key: str, nth: int = 1, **kwargs):
        super().__init__(name=name, key=key, **kwargs)
        self.nth = nth


class FindAll(_Find):
    def __init__(self, name: str, key: str, limit: int | None = None, **kwargs):
        super().__init__(name=name, key=key, **kwargs)
        self.limit = limit


class HasProperty(_Perception):
    INPUT_PORTS = {'obj': OBJECT}

    def __init__(self, name: str, property: str, value: str, **kwargs):
        super().__init__(name=name, **kwargs)
        self.property = property
        self.value = value       # as written; the executor converts True/False itself


class HasCount(_Perception):
    def __init__(self, name: str, key: str, count: int, comparison: str = 'exactly',
                 **kwargs):
        super().__init__(name=name, **kwargs)
        self.key = key
        self.count = count
        self.comparison = comparison


# The only leaf tags the parser may build. Passing this dict to the parser, instead of
# its default "auto" registry, keeps it from building any other ports class.
REGISTRY = {cls.__name__: cls for cls in (Place, Pour, Shake, Close,
                                          FindOne, FindAll, HasProperty, HasCount)}
