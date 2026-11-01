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


# "If there are two glass objects, pour the one with green liquid into the yellow box; if
# there are three, pour the one with red liquid into the yellow box."
GLASS_BY_COUNT = '''def create_behavior_tree():
    try:
        root = py_trees.composites.Sequence(name="Root", memory=True)
        find_1 = FindAll(name="FindGlassObjects", key="glass_objects", color="transparent")

        count_1 = HasCount(name="TwoGlassObjects", key="glass_objects", count=2)
        find_2 = FindOne(name="FindGreenLiquidObject", key="green_object", color="transparent", liquid_color="green")
        find_3 = FindOne(name="FindYellowBox", key="yellow_box", type="box", color="yellow")
        pour_1 = Pour(name="PourGreenIntoYellowBox", source="@green_object", target="@yellow_box")
        two_case = py_trees.composites.Sequence(name="TwoGlassObjectsCase", memory=True)
        two_case.add_children([count_1, find_2, find_3, pour_1])

        count_2 = HasCount(name="ThreeGlassObjects", key="glass_objects", count=3)
        find_4 = FindOne(name="FindRedLiquidObject", key="red_object", color="transparent", liquid_color="red")
        find_5 = FindOne(name="FindYellowBoxAgain", key="yellow_box_2", type="box", color="yellow")
        pour_2 = Pour(name="PourRedIntoYellowBox", source="@red_object", target="@yellow_box_2")
        three_case = py_trees.composites.Sequence(name="ThreeGlassObjectsCase", memory=True)
        three_case.add_children([count_2, find_4, find_5, pour_2])

        count_3 = HasCount(name="TwoGlassObjectsCheck", key="glass_objects", count=2)
        not_two = py_trees.decorators.Inverter(name="NotTwoGlassObjects", child=count_3)
        count_4 = HasCount(name="ThreeGlassObjectsCheck", key="glass_objects", count=3)
        not_three = py_trees.decorators.Inverter(name="NotThreeGlassObjects", child=count_4)
        no_case = py_trees.composites.Sequence(name="NoCaseApplies", memory=True)
        no_case.add_children([not_two, not_three])

        choose_1 = py_trees.composites.Selector(name="ChooseByGlassObjectCount", memory=True)
        choose_1.add_children([two_case, three_case, no_case])

        root.add_children([find_1, choose_1])
        return root
    except Exception as e:
        logging.error(f"Error in create_behavior_tree: {e}")
'''
