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
