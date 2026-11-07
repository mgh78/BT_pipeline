"""Decorators and condition behaviours are drawn like the other nodes.

    ../contextual-asr/venv/bin/python -m pytest tests -q
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from modules import graph, xml_tree  # noqa: E402

TREE = """<root main_tree_to_execute="MainTree">
  <BehaviorTree ID="MainTree">
    <Sequence name="Root" memory="true">
      <FindOne name="FindTube" key="tube" type="test tube"/>
      <FindOne name="FindCap" key="cap" type="test tube cap"/>
      <Retry name="RetryShake" num_failures="3">
        <Shake name="ShakeTube" obj="{tube}" times="2"/>
      </Retry>
    </Sequence>
  </BehaviorTree>
</root>"""


@pytest.fixture(scope='module')
def built():
    import py_trees
    checks, tree, _ = xml_tree.check_xml(TREE)
    assert not any(check.blocking for check in checks)
    # The prompt has no py_trees behaviours any more, but the drawing still handles any
    # py_trees node, so one is added by hand to keep that path tested.
    extra = py_trees.behaviours.SetBlackboardVariable(
        name='SetShaken', variable_name='shaken', variable_value=True, overwrite=True)
    extra.arguments = {'variable_name': 'shaken', 'variable_value': True, 'overwrite': True}
    tree.add_child(extra)
    return tree


def test_each_node_gets_its_kind(built):
    root = graph.from_py_trees(built)
    find_tube, _, retry, set_1 = root.children
    assert (find_tube.kind, find_tube.type_name) == ('perception', 'FindOne')
    assert (root.kind, retry.kind, set_1.kind) == ('sequence', 'decorator', 'behaviour')
    assert retry.children[0].kind == 'action'
    assert retry.type_name == 'Retry' and set_1.type_name == 'SetBlackboardVariable'
    assert retry.arguments == {'num_failures': '3'}


def test_the_class_name_is_shown_under_a_decorator_title(built):
    retry = graph.from_py_trees(built).children[2]
    assert retry.argument_lines == ['Retry', 'num_failures = 3']
    # An action shows only its arguments: its class is not a separate line.
    assert graph.from_py_trees(built).children[2].children[0].argument_lines[0].startswith(
        'obj = ')


def test_the_counts_include_decorators_and_behaviours(built):
    counts = graph.layout(graph.from_py_trees(built)).counts()
    assert counts['decorators'] == 1
    assert counts['behaviours'] == 1 and counts['perception'] == 2
    assert counts['nodes'] == 6      # Root, two finds, Retry, Shake, SetBlackboardVariable


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
    assert again.children[2].type_name == 'Retry'


# --- the legend ----------------------------------------------------------------

def test_the_legend_lists_only_the_node_types_in_the_tree(built):
    layout = graph.layout(graph.from_py_trees(built))
    assert [row.kind for row in layout.legend] == ['sequence', 'action', 'perception',
                                                   'decorator', 'behaviour']
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


def test_a_find_node_is_drawn_in_its_own_colour(built, tmp_path):
    layout = graph.layout(graph.from_py_trees(built))
    assert config.GRAPH_COLORS['perception_border'] in graph.to_dot(layout)
    find_tube = graph.from_py_trees(built).children[0]
    assert find_tube.argument_lines == ['FindOne', 'key = tube', 'type = test tube']


# --- the blackboard notation ------------------------------------------------------

def layout_of(*nodes):
    body = '\n'.join(f'      {node}' for node in nodes)
    text = ('<root main_tree_to_execute="MainTree">\n  <BehaviorTree ID="MainTree">\n'
            f'    <Sequence name="Root" memory="true">\n{body}\n    </Sequence>\n'
            '  </BehaviorTree>\n</root>\n')
    checks, tree, _ = xml_tree.check_xml(text)
    assert not any(check.blocking for check in checks)
    return graph.layout(graph.from_py_trees(tree))


FIND_ALL = '<FindAll name="FindEveryObject" key="objects" graspable="True"/>'
FOR_EACH = ('<ForEach name="ForEachObject" source_key="objects" target_key="object">'
            '<Shake name="ShakeObject" obj="{object}" times="1"/></ForEach>')


def test_a_tree_with_braces_and_plain_keys_explains_both():
    layout = layout_of(FIND_ALL, FOR_EACH)
    assert [row.label for row in layout.notation] == ['{key}', 'plain key']
    assert layout.notation[0].lines == [
        'the object stored under that key on the blackboard, e.g. obj = {object}']
    assert len(layout.notation[1].lines) == 2


def test_a_tree_without_braces_gets_no_brace_line():
    layout = layout_of(FIND_ALL, '<HasCount name="CountObjects" key="objects" count="2"/>')
    assert [row.kind for row in layout.notation] == ['plain']


def test_the_notation_sits_under_the_node_types_in_the_meanings_column():
    layout = layout_of(FIND_ALL, FOR_EACH)
    last_type = max(row.y for row in layout.legend)
    assert all(row.y > last_type + graph.SWATCH_HEIGHT for row in layout.notation)
    columns = {row.description_x for row in layout.legend + layout.notation}
    assert len(columns) == 1
    assert all(row.label_x == layout.legend[0].name_x for row in layout.notation)
    bottom = layout.notation[-1].y + graph.NOTATION_LINE_HEIGHT * len(layout.notation[-1].lines)
    assert bottom < layout.height


def test_the_legend_grows_by_the_notation_lines():
    root = layout_of(FIND_ALL, FOR_EACH).root
    without = graph.layout(graph.from_dict(root.as_dict()), notation=[])
    with_both = graph.layout(graph.from_dict(root.as_dict()))
    assert with_both.height - without.height == pytest.approx(
        graph.NOTATION_GAP + 3 * graph.NOTATION_LINE_HEIGHT)
    assert with_both.width >= without.width


def test_the_json_round_trip_keeps_the_notation():
    import json
    layout = layout_of(FIND_ALL, FOR_EACH)
    saved = json.loads(json.dumps({'tree': layout.root.as_dict(),
                                   'notation': [row.as_dict() for row in layout.notation]}))
    again = graph.layout(graph.from_dict(saved['tree']), graph.notation_from_json(saved))
    assert [(r.kind, r.label, r.lines) for r in again.notation] == \
        [(r.kind, r.label, r.lines) for r in layout.notation]


def test_an_older_json_without_notation_still_opens():
    saved = {'tree': layout_of(FIND_ALL, FOR_EACH).root.as_dict()}
    assert graph.notation_from_json(saved) is None
    again = graph.layout(graph.from_dict(saved['tree']), graph.notation_from_json(saved))
    assert [row.kind for row in again.notation] == ['braces', 'plain']


def test_the_png_has_room_for_the_notation(tmp_path):
    from PIL import Image
    layout = layout_of(FIND_ALL, FOR_EACH)
    graph.render_png(layout, tmp_path / 'tree.png', scale=1)
    with Image.open(tmp_path / 'tree.png') as image:
        assert image.size == (int(layout.width), int(layout.height))
