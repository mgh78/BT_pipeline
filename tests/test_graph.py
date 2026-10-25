"""Decorators and condition behaviours are drawn like the other nodes.

    ../contextual-asr/venv/bin/python -m pytest tests -q
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from modules import graph  # noqa: E402
from modules.scene import load_scene  # noqa: E402
from modules.tester import SyntaxTestStage  # noqa: E402
from test_tester import SHAKE, code  # noqa: E402


@pytest.fixture(scope='module')
def built():
    source = code(
        f'shake_1 = {SHAKE}',
        'retry_1 = py_trees.decorators.Retry(name="RetryShake", child=shake_1, '
        'num_failures=3)',
        'set_1 = py_trees.behaviours.SetBlackboardVariable(name="SetShaken", '
        'variable_name="shaken", variable_value=True, overwrite=True)',
        root_children='retry_1, set_1')
    checks, tree, _ = SyntaxTestStage().check(source, load_scene('scene8'))
    assert not any(check.blocking for check in checks)
    return tree


def test_each_node_gets_its_kind(built):
    root = graph.from_py_trees(built)
    retry, set_1 = root.children
    assert (root.kind, retry.kind, set_1.kind) == ('sequence', 'decorator', 'behaviour')
    assert retry.children[0].kind == 'action'
    assert retry.type_name == 'Retry' and set_1.type_name == 'SetBlackboardVariable'
    assert retry.arguments == {'num_failures': '3'}


def test_the_class_name_is_shown_under_a_decorator_title(built):
    retry = graph.from_py_trees(built).children[0]
    assert retry.argument_lines == ['Retry', 'num_failures = 3']
    # An action shows only its arguments: its class is not a separate line.
    assert graph.from_py_trees(built).children[0].children[0].argument_lines[0].startswith(
        'obj = ')


def test_the_counts_include_decorators_and_behaviours(built):
    counts = graph.layout(graph.from_py_trees(built)).counts()
    assert counts['decorators'] == 1 and counts['behaviours'] == 1
    assert counts['nodes'] == 4      # Root, Retry, Shake, SetBlackboardVariable


def test_the_drawing_and_the_dot_file_are_written(built, tmp_path):
    layout = graph.layout(graph.from_py_trees(built))
    graph.render_png(layout, tmp_path / 'tree.png')
    assert (tmp_path / 'tree.png').stat().st_size > 0
    dot = graph.to_dot(layout)
    assert config.GRAPH_COLORS['decorator_border'] in dot
    assert config.GRAPH_COLORS['behaviour_border'] in dot


def test_a_saved_tree_can_be_redrawn(built):
    saved = graph.from_py_trees(built).as_dict()
    again = graph.from_dict(saved)
    assert [n.kind for n in again.walk()] == [n.kind for n in graph.from_py_trees(built).walk()]
    assert again.children[0].type_name == 'Retry'


# --- the legend ----------------------------------------------------------------

def test_the_legend_lists_only_the_node_types_in_the_tree(built):
    layout = graph.layout(graph.from_py_trees(built))
    assert [row.kind for row in layout.legend] == ['sequence', 'action', 'decorator',
                                                   'behaviour']
    assert [row.name for row in layout.legend][:2] == ['Sequence', 'Action']


def test_the_legend_sits_under_the_tree_and_inside_the_drawing(built):
    layout = graph.layout(graph.from_py_trees(built))
    tree_bottom = max(node.bottom for node in layout.nodes)
    assert layout.legend_title_y > tree_bottom
    assert all(row.y > layout.legend_title_y for row in layout.legend)
    assert max(row.y + graph.SWATCH_HEIGHT for row in layout.legend) < layout.height
    # Every node and every legend line fits in the width of the drawing.
    assert all(0 <= node.left and node.right <= layout.width for node in layout.nodes)
    assert all(row.description_x < layout.width for row in layout.legend)


def test_the_meanings_line_up_in_one_column(built):
    layout = graph.layout(graph.from_py_trees(built))
    assert len({row.description_x for row in layout.legend}) == 1


def test_the_image_is_as_big_as_the_layout_with_its_legend(built, tmp_path):
    from PIL import Image
    layout = graph.layout(graph.from_py_trees(built))
    graph.render_png(layout, tmp_path / 'tree.png', scale=1)
    with Image.open(tmp_path / 'tree.png') as image:
        assert image.size == (int(layout.width), int(layout.height))


def test_the_dot_file_declares_the_legend(built):
    dot = graph.to_dot(graph.layout(graph.from_py_trees(built)))
    assert 'cluster_legend' in dot
    for kind in ('sequence', 'action', 'decorator', 'behaviour'):
        assert f'legend_{kind}' in dot
    assert 'legend_selector' not in dot          # this tree has no selector
    assert 'Condition / blackboard' in dot
