"""The Execution tab's text, on the scene6 tree of tests/test_executor.py.

    ../contextual-asr/venv/bin/python -m pytest tests -q
"""

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gui.execution_text import execution_lines, last_failure  # noqa: E402
from modules.executor import execute  # noqa: E402
from modules.mock_world import MockWorld  # noqa: E402
from modules.scene import load_scene  # noqa: E402
from test_executor import SCENE6_GRASPABLE, SCENE6_TREE, document  # noqa: E402


def lines_of(tree, scene='scene6', attempt=1):
    result = execute(tree, MockWorld.from_scene(load_scene(scene)))
    return result, execution_lines(result, attempt)


def texts(lines):
    return [text for text, _ in lines]


def styled(lines, style):
    return [text for text, line_style in lines if line_style == style]


def test_the_header():
    _, lines = lines_of(SCENE6_TREE)
    assert lines[0] == ('Attempt 1: FAILURE', 'header_FAILURE')
    assert lines[1][0] == 'Stopped: finished    Ticks: 6    Faults: 0'
    assert lines[2] == ('Last failure: PlaceUnmarkedObject (Place): brown_palette is fixed '
                        'and cannot be grasped', 'FAILURE')


def test_one_tick_heading_per_tick():
    result, lines = lines_of(SCENE6_TREE)
    assert styled(lines, 'title')[:-1] == [f'Tick {n}' for n in range(1, result['ticks'] + 1)]
    assert texts(lines).index('Tick 1') < texts(lines).index('Tick 2')


def test_node_statuses_are_coloured():
    _, lines = lines_of(SCENE6_TREE)
    assert any('[SUCCESS] FindEveryObject (FindAll)' in text for text in styled(lines, 'SUCCESS'))
    assert any('[FAILURE] ObjectIsMarked' in text for text in styled(lines, 'FAILURE'))
    assert any('[RUNNING] ForEachObject' in text for text in styled(lines, 'RUNNING'))


def test_the_write_of_objects_is_bold():
    _, lines = lines_of(SCENE6_TREE)
    writes = styled(lines, 'write')
    assert any(text.startswith('  WRITE /objects = [') and 'by FindEveryObject' in text
               for text in writes)
    assert any(text.startswith('  READ  /objects') for text in styled(lines, 'read'))
    assert ('  WRITE /objects = [white_package_1, white_marked_package_1, white_package_2, '
            'white_marked_package_2, white_package_3, brown_palette, blue_box]   '
            'by FindEveryObject') in writes


def test_new_and_changed_keys_are_marked():
    _, lines = lines_of(SCENE6_TREE)
    tick2 = texts(lines).index('Tick 2')
    assert ('  /object = white_marked_package_1   ← new', 'new') in lines[:tick2]
    assert ('  /object = white_package_2   ← changed', 'changed') in lines[tick2:]
    assert ('  /bluebox = blue_box', 'plain') in lines[tick2:]


def test_the_refusal_of_the_palette_is_red():
    _, lines = lines_of(SCENE6_TREE)
    assert styled(lines, 'refused') == [
        '  Place(obj=brown_palette, location=blue_box) REFUSED: brown_palette is fixed '
        'and cannot be grasped']


def test_the_final_table():
    _, lines = lines_of(SCENE6_TREE)
    end = texts(lines)[texts(lines).index('The table at the end'):]
    assert '  white_marked_package_1: on brown_palette' in end
    assert '  white_package_3: on blue_box' in end
    assert '  brown_palette: on the table' not in end
    assert '  nothing is closed' in end and '  nothing holds liquid' in end
    assert end[-2:] == ['Faults', '  none']


def test_a_successful_run_has_no_last_failure():
    result, lines = lines_of(SCENE6_GRASPABLE, attempt=2)
    assert lines[0] == ('Attempt 2: SUCCESS', 'header_SUCCESS')
    assert lines[2] == ('Last failure: none', 'muted')
    assert last_failure(result) == ''


def test_the_final_table_shows_caps_liquids_and_faults():
    tree = document('<FindOne name="FindTube" key="tube" type="test tube"/>',
                    '<FindOne name="FindCap" key="cap" type="test tube cap" nth="2"/>',
                    '<FindOne name="FindOther" key="other" type="test tube" nth="2"/>',
                    '<Shake name="ShakeOther" obj="{other}" times="1"/>',
                    '<Close name="CloseTube" obj="{tube}" closing_obj="{cap}"/>')
    _, lines = lines_of(tree, scene='scene8')
    assert '  transparent_test_tube_1, by yellow_test_tube_cap_2' in texts(lines)
    assert '  transparent_test_tube_2: transparent red (spilled)' in texts(lines)
    assert any('ok, fault spill' in text for text in styled(lines, 'fault'))
    assert '  spill: transparent_test_tube_2 was shaken while open and spilled' in \
        styled(lines, 'fault')
    assert lines[1][0].endswith('Faults: 1')


def test_an_error_is_the_last_failure():
    tree = document('<FindAll name="FindCups" key="cups" type="cup"/>',
                    '<FindOne name="FindBox" key="box" type="box"/>',
                    '<ForEach name="ForEachCup" source_key="cups" target_key="cup">'
                    '<Place name="PlaceCup" obj="{cup}" location="{box}"/></ForEach>')
    _, lines = lines_of(tree)
    assert lines[0] == ('Attempt 1: ERROR', 'header_ERROR')
    assert lines[2][0].startswith('Last failure: NoDataAvailable')


def test_the_text_needs_no_customtkinter():
    code = ('import sys; sys.modules["customtkinter"] = None; '
            'import gui.execution_text; print("ok")')
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    done = subprocess.run([sys.executable, '-c', code], cwd=root, capture_output=True,
                          text=True)
    assert done.stdout.strip() == 'ok', done.stderr
