"""Stage 6 - draw the behavior tree.

One layout, three outputs. The layout is computed once from the built py_trees tree
and is then used by

* the canvas in the interface, which is interactive;
* ``bt_graph.png``, drawn with Pillow so it needs nothing installed beyond Pillow;
* ``bt_graph.dot``, which is written always, and rendered with graphviz as
  ``bt_graph_graphviz.png`` when the ``dot`` binary happens to be available.

Nodes are drawn with the usual behavior tree conventions: a sequence carries an arrow,
a selector a question mark, and actions are rounded boxes listing their arguments. A
decorator is drawn in its own colour with its class name under the title, and the
condition and blackboard behaviours are drawn the same way.
"""

import html
import json
import shutil
import subprocess
from dataclasses import dataclass, field

import config
from core.pipeline import Stage, StageError, StageStatus

# Layout constants, in pixels at scale 1.
HORIZONTAL_GAP = 26
VERTICAL_GAP = 46
MIN_WIDTH = 120
MAX_WIDTH = 330
PADDING = 14
TITLE_HEIGHT = 24
ARGUMENT_HEIGHT = 16
MARGIN = 30
TITLE_CHAR_WIDTH = 7.6     # approximate advance of the title font
ARGUMENT_CHAR_WIDTH = 6.2  # approximate advance of the argument font

MARKERS = {'sequence': '\u2192', 'selector': '?', 'action': '', 'decorator': '',
           'behaviour': ''}


@dataclass
class GraphNode:
    """One box in the drawing, with its place in the layout."""

    id: str
    label: str
    kind: str                      # 'sequence', 'selector', 'action', 'decorator', 'behaviour'
    arguments: dict = field(default_factory=dict)
    type_name: str = ''            # the py_trees class, shown for decorators and behaviours
    children: list = field(default_factory=list)
    x: float = 0.0                 # centre of the box
    y: float = 0.0                 # top of the box
    width: float = MIN_WIDTH
    height: float = TITLE_HEIGHT
    subtree_width: float = MIN_WIDTH

    @property
    def marker(self):
        return MARKERS.get(self.kind, '')

    @property
    def argument_lines(self):
        lines = [f'{key} = {value}' for key, value in self.arguments.items()]
        if self.kind in ('decorator', 'behaviour') and self.type_name:
            lines.insert(0, self.type_name)
        return lines

    @property
    def left(self):
        return self.x - self.width / 2

    @property
    def right(self):
        return self.x + self.width / 2

    @property
    def bottom(self):
        return self.y + self.height

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()

    def as_dict(self):
        return {
            'id': self.id, 'label': self.label, 'kind': self.kind,
            'type_name': self.type_name, 'arguments': self.arguments,
            'children': [child.as_dict() for child in self.children],
        }


@dataclass
class GraphLayout:
    """A laid-out tree: the root box plus the size of the drawing around it."""

    root: GraphNode
    width: float
    height: float

    @property
    def nodes(self):
        return list(self.root.walk())

    @property
    def edges(self):
        return [(parent, child) for parent in self.nodes for child in parent.children]

    def counts(self):
        nodes = self.nodes
        return {
            'nodes': len(nodes),
            'actions': sum(1 for n in nodes if n.kind == 'action'),
            'sequences': sum(1 for n in nodes if n.kind == 'sequence'),
            'selectors': sum(1 for n in nodes if n.kind == 'selector'),
            'decorators': sum(1 for n in nodes if n.kind == 'decorator'),
            'behaviours': sum(1 for n in nodes if n.kind == 'behaviour'),
            'depth': _depth(self.root),
        }


def _depth(node):
    return 1 + max((_depth(child) for child in node.children), default=0)


# --- Building and laying out --------------------------------------------------

def _is_decorator(node):
    import py_trees
    return isinstance(node, py_trees.decorators.Decorator)


def from_py_trees(root, prefix='n'):
    """Convert a built py_trees tree into GraphNodes."""
    counter = [0]

    def convert(node):
        counter[0] += 1
        type_name = type(node).__name__
        if type_name == 'Sequence':
            kind = 'sequence'
        elif type_name == 'Selector':
            kind = 'selector'
        elif _is_decorator(node):
            kind = 'decorator'
        elif hasattr(node, 'action'):      # the four actions; see tester._sandbox
            kind = 'action'
        else:
            kind = 'behaviour'
        arguments = {key: value for key, value in
                     (getattr(node, 'arguments', None) or {}).items() if key != 'name'}
        graph_node = GraphNode(id=f'{prefix}{counter[0]}', label=node.name, kind=kind,
                               arguments={k: str(v) for k, v in arguments.items()},
                               type_name=type_name)
        graph_node.children = [convert(child) for child in getattr(node, 'children', [])]
        return graph_node

    return convert(root)


def from_dict(payload, prefix='n'):
    """Rebuild GraphNodes from ``bt_graph.json``, so a past run can be redrawn."""
    counter = [0]

    def convert(entry):
        counter[0] += 1
        node = GraphNode(id=f'{prefix}{counter[0]}', label=entry['label'],
                         kind=entry['kind'], arguments=entry.get('arguments', {}),
                         type_name=entry.get('type_name', ''))
        node.children = [convert(child) for child in entry.get('children', [])]
        return node

    return convert(payload)


def layout(root):
    """Place every node: parents centred over their children, siblings left to right."""

    def measure(node):
        title = len(node.label) + (2 if node.marker else 0)
        widest_argument = max((len(line) for line in node.argument_lines), default=0)
        node.width = min(MAX_WIDTH, max(
            MIN_WIDTH,
            title * TITLE_CHAR_WIDTH + 2 * PADDING,
            widest_argument * ARGUMENT_CHAR_WIDTH + 2 * PADDING))
        node.height = TITLE_HEIGHT + ARGUMENT_HEIGHT * len(node.argument_lines) + PADDING
        for child in node.children:
            measure(child)
        if node.children:
            spread = (sum(child.subtree_width for child in node.children)
                      + HORIZONTAL_GAP * (len(node.children) - 1))
            node.subtree_width = max(node.width, spread)
        else:
            node.subtree_width = node.width

    def place(node, left, top):
        node.y = top
        if not node.children:
            node.x = left + node.subtree_width / 2
            return
        spread = (sum(child.subtree_width for child in node.children)
                  + HORIZONTAL_GAP * (len(node.children) - 1))
        cursor = left + (node.subtree_width - spread) / 2
        for child in node.children:
            place(child, cursor, top + node.height + VERTICAL_GAP)
            cursor += child.subtree_width + HORIZONTAL_GAP
        node.x = (node.children[0].x + node.children[-1].x) / 2

    measure(root)
    place(root, MARGIN, MARGIN)
    width = root.subtree_width + 2 * MARGIN
    height = max(node.bottom for node in root.walk()) + MARGIN
    return GraphLayout(root=root, width=width, height=height)


# --- Pillow rendering ---------------------------------------------------------

FONT_CANDIDATES = (
    '/System/Library/Fonts/Supplemental/Arial Bold.ttf',
    '/System/Library/Fonts/Supplemental/Arial.ttf',
    '/System/Library/Fonts/Helvetica.ttc',
    '/Library/Fonts/Arial.ttf',
    'C:/Windows/Fonts/segoeui.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
)


def _font(size, bold=False):
    from PIL import ImageFont

    candidates = FONT_CANDIDATES if bold else FONT_CANDIDATES[1:]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def render_png(graph_layout, path, scale=2):
    """Draw the layout to a PNG. ``scale`` of 2 gives a sharp image on any screen."""
    from PIL import Image, ImageDraw

    colors = config.GRAPH_COLORS
    image = Image.new('RGB', (int(graph_layout.width * scale), int(graph_layout.height * scale)),
                      colors['background'])
    draw = ImageDraw.Draw(image)
    title_font = _font(int(13 * scale), bold=True)
    argument_font = _font(int(11 * scale))

    # Edges first, so the boxes sit on top of them.
    for parent, child in graph_layout.edges:
        middle = (parent.bottom + child.y) / 2
        draw.line([(parent.x * scale, parent.bottom * scale),
                   (parent.x * scale, middle * scale),
                   (child.x * scale, middle * scale),
                   (child.x * scale, child.y * scale)],
                  fill=colors['edge'], width=max(1, int(1.6 * scale)))

    for node in graph_layout.nodes:
        fill = colors[f'{node.kind}_fill']
        border = colors[f'{node.kind}_border']
        box = [node.left * scale, node.y * scale, node.right * scale, node.bottom * scale]
        draw.rounded_rectangle(box, radius=int(7 * scale), fill=fill, outline=border,
                               width=max(1, int(1.6 * scale)))

        title = f'{node.marker} {node.label}' if node.marker else node.label
        draw.text((node.x * scale, (node.y + TITLE_HEIGHT / 2 + 3) * scale), title,
                  font=title_font, fill=colors['text'], anchor='mm')

        offset = node.y + TITLE_HEIGHT + 8
        for line in node.argument_lines:
            draw.text(((node.left + PADDING) * scale, offset * scale), line,
                      font=argument_font, fill=colors['subtext'], anchor='lm')
            offset += ARGUMENT_HEIGHT

    image.save(path)
    return path


# --- DOT and graphviz ---------------------------------------------------------

SHAPES = {'sequence': 'box', 'selector': 'box', 'action': 'box', 'decorator': 'box',
          'behaviour': 'box'}


def to_dot(graph_layout, title=''):
    """Return the graph as DOT source. Written always; renderable wherever dot exists."""
    colors = config.GRAPH_COLORS
    lines = ['digraph behavior_tree {',
             '    graph [rankdir=TB, bgcolor="#ffffff", splines=ortho, nodesep=0.35, '
             'ranksep=0.55];',
             '    node  [fontname="Helvetica", fontsize=11, style="rounded,filled"];',
             '    edge  [color="#666666", arrowsize=0.7];']
    if title:
        lines.append(f'    labelloc="t"; label="{html.escape(title)}"; '
                     f'fontname="Helvetica"; fontsize=13;')

    for node in graph_layout.nodes:
        marker = f'{node.marker} ' if node.marker else ''
        label = html.escape(f'{marker}{node.label}')
        if node.argument_lines:
            label += '<BR/><FONT POINT-SIZE="9" COLOR="#444444">'
            label += '<BR/>'.join(html.escape(line) for line in node.argument_lines)
            label += '</FONT>'
        lines.append(
            f'    {node.id} [label=<{label}>, shape={SHAPES[node.kind]}, '
            f'fillcolor="{_light(colors[f"{node.kind}_fill"])}", '
            f'color="{colors[f"{node.kind}_border"]}"];')

    for parent, child in graph_layout.edges:
        lines.append(f'    {parent.id} -> {child.id};')
    lines.append('}')
    return '\n'.join(lines)


def _light(hex_color):
    """Lighten a canvas colour so it reads on the white background graphviz uses."""
    value = hex_color.lstrip('#')
    red, green, blue = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    mix = lambda channel: int(channel + (255 - channel) * 0.72)  # noqa: E731
    return f'#{mix(red):02x}{mix(green):02x}{mix(blue):02x}'


def graphviz_available():
    return shutil.which('dot') is not None


def render_graphviz(dot_source, path, output_format='png'):
    """Render DOT with the system graphviz. Returns the path, or None when it cannot."""
    if not graphviz_available():
        return None
    try:
        completed = subprocess.run(
            ['dot', f'-T{output_format}', '-o', str(path)],
            input=dot_source.encode('utf-8'),
            capture_output=True, timeout=30, check=False)
        if completed.returncode != 0:
            return None
    except (OSError, subprocess.TimeoutExpired):
        return None
    return path


# --- The stage ----------------------------------------------------------------

class TreeGraphStage(Stage):
    """Lay out the built tree and save it as a picture, a DOT file and JSON."""

    name = 'graph'
    title = 'Tree graph'
    description = 'Draw the behavior tree and save it as an image.'

    def execute(self, context, payload):
        root = payload.get('tree')
        if root is None:
            raise StageError('There is no built tree to draw — the syntax check must '
                             'pass first.')

        graph_layout = layout(from_py_trees(root))
        payload['graph_layout'] = graph_layout
        counts = graph_layout.counts()

        artifacts = {}
        png_path = context.path('bt_graph.png')
        render_png(graph_layout, png_path)
        artifacts['tree image'] = png_path
        payload['graph_png'] = png_path
        self.log.info('drew %d nodes (%d actions, depth %d) to %s',
                      counts['nodes'], counts['actions'], counts['depth'], png_path.name)

        artifacts['tree structure'] = context.write_json(
            'bt_graph.json', {'counts': counts, 'tree': graph_layout.root.as_dict()})

        detail = dict(counts)
        if config.GRAPH_EXPORT_DOT:
            dot_source = to_dot(graph_layout, title=payload.get('generator_input', ''))
            artifacts['dot source'] = context.write_text('bt_graph.dot', dot_source)

            if config.GRAPH_EXPORT_GRAPHVIZ:
                if graphviz_available():
                    rendered = render_graphviz(
                        dot_source,
                        context.path(f'bt_graph_graphviz.{config.GRAPH_EXPORT_FORMAT}'),
                        config.GRAPH_EXPORT_FORMAT)
                    if rendered:
                        artifacts['graphviz image'] = rendered
                        detail['graphviz'] = 'rendered'
                        self.log.info('graphviz rendered %s', rendered.name)
                    else:
                        detail['graphviz'] = 'dot failed — the .dot file is still saved'
                        self.log.warning('graphviz could not render the .dot file')
                else:
                    detail['graphviz'] = ('not installed — install it with '
                                          '`brew install graphviz` to also get a '
                                          'graphviz image')
                    self.log.info('the dot binary is not installed; wrote bt_graph.dot only')

        return self.result(
            StageStatus.PASSED,
            summary=f'{counts["nodes"]} nodes, depth {counts["depth"]}',
            detail=detail, artifacts=artifacts)
