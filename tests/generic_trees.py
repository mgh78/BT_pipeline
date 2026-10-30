"""Helpers for tests of generic trees: objects are found at run time and used by @key."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.tester import SyntaxTestStage  # noqa: E402


def code(*lines, root_children):
    """A create_behavior_tree() whose body is ``lines``, then the root's children."""
    body = '\n'.join(f'        {line}' for line in lines)
    return ('def create_behavior_tree():\n'
            '    try:\n'
            '        root = py_trees.composites.Sequence(name="Root", memory=True)\n'
            f'{body}\n'
            f'        root.add_children([{root_children}])\n'
            '        return root\n'
            '    except Exception as e:\n'
            '        logging.error(f"Error in create_behavior_tree: {e}")\n')


def run_checks(source):
    checks, tree, _ = SyntaxTestStage().check(source)
    return {check.id: check for check in checks}, tree


def failures(checks):
    return sorted(check_id for check_id, check in checks.items() if check.blocking)


RACK = 'find_1 = FindOne(name="FindRack", key="rack", type="box", color="blue")'
FLASKS = 'find_2 = FindAll(name="FindFlasks", key="flasks", type="measuring cylinder")'
PLACE = 'place_1 = Place(name="PlaceFlask", obj="@flask", location="@rack")'
LOOP = ('for_1 = py_trees.decorators.ForEach(name="ForEachFlask", child=place_1, '
        'source_key="flasks", target_key="flask")')


def flasks_into_rack(*extra):
    """Put every measuring cylinder into the blue box."""
    return code(RACK, FLASKS, PLACE, LOOP, *extra, root_children='find_1, find_2, for_1')
