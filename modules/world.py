"""The world a behavior tree acts on: what an object is, and what a world can do.

The tree's nodes only ever talk to a ``World``. The mock world (``modules/mock_world.py``)
and, later, the Unity simulator both implement it, so one can replace the other without
touching the nodes.
"""

import abc
from dataclasses import asdict, dataclass, field


@dataclass(repr=False)
class WorldObject:
    """One object on the table.

    The field names are the perception property names (prompts/perception.txt), so a
    node can read a property with ``getattr(obj, property)``.
    """

    id: str
    type: str
    color: str
    liquid_color: str = ''        # '' when it holds no liquid
    graspable: bool = True
    holds_liquid: bool = False
    closed: bool = False
    marked: bool = False
    position: dict = field(default_factory=dict)   # {'x', 'y', 'z'} in metres
    on: str | None = None         # id of the object it was placed on or in
    closed_by: str | None = None  # id of the cap that closes it
    spilled: bool = False         # liquid was spilled from it

    def __repr__(self):
        return self.id

    def as_dict(self):
        """Every field as plain JSON-ready data."""
        return asdict(self)


@dataclass
class Outcome:
    """The result of an action.

    ``ok`` is False when the action could not be carried out; ``reason`` then says why in
    one sentence that names the objects. ``fault`` names something that went physically
    wrong although the action was carried out (for example "spill"); '' otherwise.
    """

    ok: bool
    reason: str = ''
    fault: str = ''


class World(abc.ABC):
    """What a world can do. The tree's nodes use only these methods."""

    @abc.abstractmethod
    def perceive(self, properties: dict, position: str | None = None) -> list[WorldObject]:
        """Every object that has all these properties, in order (see the ordering rule).

        The ordering rule, as in prompts/semantic_judge_prompt.txt:
        - without position: scan order, lowest y first, then lowest x;
        - "leftmost": lowest y first;
        - "rightmost": highest y first;
        - "nearest": lowest x first;
        - "farthest": highest x first.
        """

    @abc.abstractmethod
    def place(self, obj: WorldObject, location: WorldObject) -> Outcome:
        """Put obj at location."""

    @abc.abstractmethod
    def pour(self, source: WorldObject, target: WorldObject) -> Outcome:
        """Pour the liquid in source into target."""

    @abc.abstractmethod
    def shake(self, obj: WorldObject, times: int) -> Outcome:
        """Shake obj the given number of times."""

    @abc.abstractmethod
    def close(self, obj: WorldObject, closing_obj: WorldObject) -> Outcome:
        """Close obj with closing_obj."""

    @abc.abstractmethod
    def snapshot(self) -> dict:
        """The whole table as JSON-ready data: every object's as_dict(), and every fault so far."""

    @abc.abstractmethod
    def take_events(self) -> list[dict]:
        """The actions carried out since the last call, oldest first, then forget them.
        Each is {'action', 'arguments', 'ok', 'reason', 'fault'}."""
