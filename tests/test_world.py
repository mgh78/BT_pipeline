"""The world interface the tree's nodes use.

    ../contextual-asr/venv/bin/python -m pytest tests -q
"""

import dataclasses
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from modules.world import World, WorldObject  # noqa: E402


def test_field_names_are_the_perception_properties():
    fields = {f.name for f in dataclasses.fields(WorldObject)}
    wanted = {'type', *config.PERCEPTION_COLOR_PROPERTIES, *config.PERCEPTION_BOOLEAN_PROPERTIES}
    assert wanted <= fields


def test_world_cannot_be_instantiated():
    with pytest.raises(TypeError):
        World()


def test_repr_is_the_id_and_as_dict_is_json_ready():
    obj = WorldObject(id='red_cube', type='cube', color='red',
                      position={'x': 0.6, 'y': 0.05, 'z': 0.03})
    assert repr(obj) == 'red_cube'
    assert repr([obj]) == '[red_cube]'
    data = json.loads(json.dumps(obj.as_dict()))
    assert data['id'] == 'red_cube' and data['position']['y'] == 0.05 and data['on'] is None
