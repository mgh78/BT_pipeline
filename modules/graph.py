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
condition and blackboard behaviours are drawn the same way. A legend under the tree
names the colour and symbol of every node type that appears in it.
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

# The node types, in the order the legend lists them: (kind, name, what it means).
LEGEND = (
    ('sequence', 'Sequence', 'runs its children in order and stops at the first failure'),
    ('selector', 'Selector', 'tries its children in order until one succeeds'),
    ('action', 'Action', 'a robot action: Place, Pour, Shake or Close'),
    ('perception', 'Find / check',
     'finds objects by their properties, or checks a property or how many were found'),
    ('decorator', 'Decorator',
     'wraps the node under it and changes how it runs or what it returns'),
    ('behaviour', 'Condition / blackboard',
     'checks or sets a blackboard value, or always succeeds or fails'),
)
# The blackboard notation in the node arguments, listed under the node types when the tree
# uses it: (kind, label, the lines that explain it).
NOTATION = (
    ('braces', '{key}',
     ('a value read from the blackboard: obj = {object}, source_key = {objects}',)),
    ('plain', 'plain key',
     ('where a find node or ForEach writes: key = objects, target_key = object',
      "(in the XML, source_key and HasCount's key are written without braces)")),
)
PLAIN_KEY_ARGUMENTS = ('key', 'target_key')
# Keys a node reads although the XML writes them plain. The drawing shows them in braces,
# so braces always mean "read from the blackboard"; node.arguments and the XML keep them
# plain, and the judge reads them that way.
READ_KEYS = {'ForEach': ('source_key',), 'HasCount': ('key',)}
LEGEND_TITLE_HEIGHT = 22
NOTATION_GAP = 6               # between the node types and the notation
NOTATION_LINE_HEIGHT = 18
LEGEND_ROW_HEIGHT = 26
LEGEND_GAP = 16                # between the tree and its legend
SWATCH_WIDTH = 36
SWATCH_HEIGHT = 18
SWATCH_TEXT_GAP = 10

MARKERS = {'sequence': '\u2192', 'selector': '?', 'action': '', 'perception': '',
           'decorator': '', 'behaviour': ''}


@dataclass
class GraphNode:
    """One box in the drawing, with its place in the layout."""

    id: str
    label: str
    kind: str                      # 'sequence', 'selector', 'action', 'perception',
                                   # 'decorator' or 'behaviour'
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
        if self.kind in ('perception', 'decorator', 'behaviour') and self.type_name:
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
class LegendRow:
    """One line of the legend: a swatch in the node's colours, its name and its meaning."""

    kind: str
    name: str
    description: str
    x: float                       # left edge of the swatch
    y: float                       # top of the swatch
    name_x: float
    description_x: float


@dataclass
class NotationRow:
    """One notation entry of the legend: no swatch, its label and the lines that explain it."""

    kind: str
    label: str
    lines: list
    y: float                       # top of the first line
    label_x: float
    description_x: float

    def line_middles(self):
        """The vertical middle of each line, for drawing it with a left-middle anchor."""
        return [self.y + (index + 0.5) * NOTATION_LINE_HEIGHT for index in range(len(self.lines))]

    def as_dict(self):
        return {'kind': self.kind, 'label': self.label, 'lines': list(self.lines)}


@dataclass
class GraphLayout:
    """A laid-out tree: the root box plus the size of the drawing around it.

    The drawing also holds the legend under the tree, so ``width`` and ``height`` include
    it and every renderer draws the same picture.
    """

    root: GraphNode
    width: float
    height: float
    legend: list = field(default_factory=list)
    legend_title_y: float = 0.0
    notation: list = field(default_factory=list)

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
            'perception': sum(1 for n in nodes if n.kind == 'perception'),
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


def shown_arguments(type_name, arguments):
    """A node's arguments as the drawing shows them: the keys it reads in braces."""
    read = READ_KEYS.get(type_name, ())
    return {key: f'{{{value}}}' if key in read and not str(value).startswith('{') else value
            for key, value in arguments.items()}


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
        elif hasattr(node, 'action'):      # the four actions; see bt_nodes.py
            kind = 'action'
        elif hasattr(node, 'perception'):  # FindOne, FindAll, HasProperty, HasCount
            kind = 'perception'
        else:
            kind = 'behaviour'
        arguments = {key: value for key, value in
                     (getattr(node, 'arguments', None) or {}).items() if key != 'name'}
        graph_node = GraphNode(id=f'{prefix}{counter[0]}', label=node.name, kind=kind,
                               arguments=shown_arguments(
                                   type_name, {k: str(v) for k, v in arguments.items()}),
                               type_name=type_name)
        graph_node.children = [convert(child) for child in getattr(node, 'children', [])]
        return graph_node

    return convert(root)


def from_dict(payload, prefix='n'):
    """Rebuild GraphNodes from ``bt_graph.json``, so a past run can be redrawn."""
    counter = [0]

    def convert(entry):
        counter[0] += 1
        type_name = entry.get('type_name', '')
        node = GraphNode(id=f'{prefix}{counter[0]}', label=entry['label'],
                         kind=entry['kind'], type_name=type_name,
                         arguments=shown_arguments(type_name, entry.get('arguments', {})))
        node.children = [convert(child) for child in entry.get('children', [])]
        return node

    return convert(payload)


def notation_for(root):
    """The NOTATION entries this tree uses: {key} when an argument is shown in braces,
    the plain key when a find node or ForEach writes a key."""
    nodes = list(root.walk())
    used = set()
    if any('{' in str(value) for node in nodes for value in node.arguments.values()):
        used.add('braces')
    if any(not str(node.arguments.get(name, '{')).startswith('{')
           for node in nodes for name in PLAIN_KEY_ARGUMENTS):
        used.add('plain')
    return [entry for entry in NOTATION if entry[0] in used]


def notation_from_json(payload):
    """The notation saved in bt_graph.json, or None for a file written before it existed."""
    saved = payload.get('notation')
    if saved is None:
        return None
    return [(entry['kind'], entry['label'], tuple(entry['lines'])) for entry in saved]


def layout(root, notation=None):
    """Place every node: parents centred over their children, siblings left to right.

    ``notation`` is the list of NOTATION entries to explain under the node types; None
    works it out from the tree.
    """

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
    tree_width = root.subtree_width + 2 * MARGIN
    tree_height = max(node.bottom for node in root.walk()) + MARGIN

    # The legend names only the node types this tree uses.
    kinds = {node.kind for node in root.walk()}
    legend_title_y = tree_height + LEGEND_GAP
    rows, legend_width = [], 0.0
    top = legend_title_y + LEGEND_TITLE_HEIGHT
    entries = [entry for entry in LEGEND if entry[0] in kinds]
    notation = notation_for(root) if notation is None else notation
    name_x = MARGIN + SWATCH_WIDTH + SWATCH_TEXT_GAP
    # One column for the meanings, so they line up whatever the names' lengths.
    description_x = name_x + max(
        [len(name) * TITLE_CHAR_WIDTH for _, name, _ in entries]
        + [len(label) * ARGUMENT_CHAR_WIDTH for _, label, _ in notation],
        default=0) + SWATCH_TEXT_GAP
    for kind, name, description in entries:
        rows.append(LegendRow(kind, name, description, MARGIN, top, name_x, description_x))
        legend_width = max(legend_width,
                           description_x + len(description) * ARGUMENT_CHAR_WIDTH + MARGIN)
        top += LEGEND_ROW_HEIGHT

    notation_rows = []
    if notation:
        top += NOTATION_GAP
    for kind, label, lines in notation:
        notation_rows.append(NotationRow(kind, label, list(lines), top, name_x, description_x))
        legend_width = max([legend_width] + [
            description_x + len(line) * ARGUMENT_CHAR_WIDTH + MARGIN for line in lines])
        top += NOTATION_LINE_HEIGHT * len(lines)

    width = max(tree_width, legend_width)
    for node in root.walk():           # centre the tree when the legend is the wider one
        node.x += (width - tree_width) / 2
    height = top + MARGIN / 2
    return GraphLayout(root=root, width=width, height=height, legend=rows,
                       legend_title_y=legend_title_y, notation=notation_rows)


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

    _draw_legend(draw, graph_layout, colors, scale, title_font, argument_font)

    image.save(path)
    return path


def _draw_legend(draw, graph_layout, colors, scale, title_font, argument_font):
    """The legend under the tree: what each colour and symbol stands for."""
    if not graph_layout.legend:
        return
    draw.text((MARGIN * scale, (graph_layout.legend_title_y + LEGEND_TITLE_HEIGHT / 2) * scale),
              'Legend', font=title_font, fill=colors['subtext'], anchor='lm')
    for row in graph_layout.legend:
        middle = (row.y + SWATCH_HEIGHT / 2) * scale
        draw.rounded_rectangle(
            [row.x * scale, row.y * scale, (row.x + SWATCH_WIDTH) * scale,
             (row.y + SWATCH_HEIGHT) * scale],
            radius=int(5 * scale), fill=colors[f'{row.kind}_fill'],
            outline=colors[f'{row.kind}_border'], width=max(1, int(1.6 * scale)))
        marker = MARKERS.get(row.kind, '')
        if marker:
            draw.text(((row.x + SWATCH_WIDTH / 2) * scale, middle), marker,
                      font=title_font, fill=colors['text'], anchor='mm')
        draw.text((row.name_x * scale, middle), row.name, font=title_font,
                  fill=colors['text'], anchor='lm')
        draw.text((row.description_x * scale, middle), row.description,
                  font=argument_font, fill=colors['subtext'], anchor='lm')
    for row in graph_layout.notation:
        middles = row.line_middles()
        draw.text((row.label_x * scale, middles[0] * scale), row.label, font=argument_font,
                  fill=colors['text'], anchor='lm')
        for line, middle in zip(row.lines, middles):
            draw.text((row.description_x * scale, middle * scale), line, font=argument_font,
                      fill=colors['subtext'], anchor='lm')


# --- DOT and graphviz ---------------------------------------------------------

SHAPES = {'sequence': 'box', 'selector': 'box', 'action': 'box', 'perception': 'box',
          'decorator': 'box',
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

    if graph_layout.legend:
        lines += ['    subgraph cluster_legend {',
                  '        label="Legend"; fontname="Helvetica"; fontsize=10; '
                  'style="rounded"; color="#bbbbbb";']
        previous = None
        for row in graph_layout.legend:
            marker = f'{MARKERS[row.kind]} ' if MARKERS.get(row.kind) else ''
            text = html.escape(f'{marker}{row.name}')
            lines.append(
                f'        legend_{row.kind} [label=<{text}<BR/><FONT POINT-SIZE="9" '
                f'COLOR="#444444">{html.escape(row.description)}</FONT>>, shape=box, '
                f'fillcolor="{_light(colors[f"{row.kind}_fill"])}", '
                f'color="{colors[f"{row.kind}_border"]}"];')
            if previous:
                lines.append(f'        {previous} -> legend_{row.kind} [style=invis];')
            previous = f'legend_{row.kind}'
        lines.append('    }')
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
            'bt_graph.json', {'counts': counts, 'tree': graph_layout.root.as_dict(),
                              'notation': [row.as_dict() for row in graph_layout.notation]})

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
