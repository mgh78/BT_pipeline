"""The behavior tree, drawn on a canvas you can zoom, pan and click.

It draws the same :class:`~modules.graph.GraphLayout` that the PNG export uses, so
what you see here and what is saved to the run directory are the same picture.
"""

import tkinter

import customtkinter

import config
from modules import graph as graph_module
from gui.stage_panel import open_path

MONOSPACE = ('Menlo', 11)


class GraphView(customtkinter.CTkFrame):
    """A canvas showing one behavior tree, with a toolbar and a selection line."""

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.layout = None
        self.scale = 1.0
        self.image_path = None
        self._items = {}        # canvas item id -> GraphNode
        self._drag_origin = None

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        toolbar = customtkinter.CTkFrame(self, fg_color='transparent')
        toolbar.grid(row=0, column=0, sticky='ew', padx=8, pady=(8, 4))

        for text, command in (('−', lambda: self.zoom(0.8)),
                              ('+', lambda: self.zoom(1.25)),
                              ('Fit', self.fit)):
            customtkinter.CTkButton(toolbar, text=text, width=38, height=26,
                                    font=('Arial', 12), command=command).pack(side='left',
                                                                              padx=(0, 4))

        self.open_button = customtkinter.CTkButton(
            toolbar, text='Open image', width=96, height=26, font=('Arial', 11),
            fg_color='#2b3a4a', hover_color='#36506b', state='disabled',
            command=self._open_image)
        self.open_button.pack(side='right')

        self.counts_label = customtkinter.CTkLabel(
            toolbar, text='', text_color='gray60', font=('Arial', 11))
        self.counts_label.pack(side='right', padx=10)

        self.canvas = tkinter.Canvas(
            self, bg=config.GRAPH_COLORS['background'], highlightthickness=0, bd=0)
        self.canvas.grid(row=1, column=0, sticky='nsew', padx=8, pady=4)

        self.selection_label = customtkinter.CTkLabel(
            self, text='Generate a tree to see it here.', anchor='w', justify='left',
            font=MONOSPACE, text_color='gray60', wraplength=520)
        self.selection_label.grid(row=2, column=0, sticky='ew', padx=12, pady=(0, 10))

        self.canvas.bind('<Button-1>', self._on_click)
        self.canvas.bind('<B1-Motion>', self._on_drag)
        self.canvas.bind('<ButtonRelease-1>', lambda _event: setattr(self, '_drag_origin', None))
        self.canvas.bind('<MouseWheel>', self._on_wheel)
        self.canvas.bind('<Configure>', lambda _event: self._redraw())

    # --- Public ---------------------------------------------------------

    def show(self, layout, image_path=None):
        """Draw a laid-out tree."""
        self.layout = layout
        self.image_path = image_path
        self.open_button.configure(state='normal' if image_path else 'disabled')
        counts = layout.counts()
        self.counts_label.configure(
            text=f'{counts["nodes"]} nodes · {counts["actions"]} actions · '
                 f'depth {counts["depth"]}')
        self.selection_label.configure(text='Click a node to see its arguments.',
                                       text_color='gray60')
        self.fit()

    def show_from_json(self, payload, image_path=None):
        """Draw a tree stored in bt_graph.json, for a run that has already finished."""
        root = graph_module.from_dict(payload['tree'])
        self.show(graph_module.layout(root), image_path)

    def clear(self, message='Generate a tree to see it here.'):
        self.layout = None
        self.image_path = None
        self._items = {}
        self.canvas.delete('all')
        self.counts_label.configure(text='')
        self.open_button.configure(state='disabled')
        self.selection_label.configure(text=message, text_color='gray60')

    # --- Zooming --------------------------------------------------------

    def zoom(self, factor):
        if not self.layout:
            return
        self.scale = max(0.25, min(3.0, self.scale * factor))
        self._redraw()

    def fit(self):
        if not self.layout:
            return
        width = max(self.canvas.winfo_width(), 1)
        height = max(self.canvas.winfo_height(), 1)
        if width < 50 or height < 50:  # the canvas has not been sized yet
            self.after(60, self.fit)
            return
        self.scale = max(0.25, min(1.6, min(width / self.layout.width,
                                            height / self.layout.height)))
        self._redraw()
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)

    def _on_wheel(self, event):
        self.zoom(1.1 if event.delta > 0 else 0.9)

    # --- Panning and selection ------------------------------------------

    def _on_click(self, event):
        self._drag_origin = (event.x, event.y)
        self.canvas.scan_mark(event.x, event.y)
        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        for item in reversed(self.canvas.find_overlapping(x, y, x, y)):
            node = self._items.get(item)
            if node:
                self._select(node)
                return

    def _on_drag(self, event):
        if self._drag_origin:
            self.canvas.scan_dragto(event.x, event.y, gain=1)

    def _select(self, node):
        kind = {'sequence': 'Sequence', 'selector': 'Selector', 'decorator': 'Decorator',
                'behaviour': 'Condition / blackboard'}.get(node.kind, 'Action')
        text = f'{kind}  ·  {node.label}'
        if node.kind in ('decorator', 'behaviour') and node.type_name:
            text += f'  ({node.type_name})'
        if node.arguments:
            text += '\n' + '\n'.join(f'    {k} = {v}' for k, v in node.arguments.items())
        if node.children:
            text += f'\n    {len(node.children)} child' \
                    f'{"ren" if len(node.children) > 1 else ""}: ' \
                    + ', '.join(child.label for child in node.children)
        self.selection_label.configure(text=text, text_color='gray80')

    def _open_image(self):
        if self.image_path:
            open_path(self.image_path)

    # --- Drawing --------------------------------------------------------

    def _redraw(self):
        self.canvas.delete('all')
        self._items = {}
        if not self.layout:
            return

        colors = config.GRAPH_COLORS
        scale = self.scale

        for parent, child in self.layout.edges:
            middle = (parent.bottom + child.y) / 2
            self.canvas.create_line(
                parent.x * scale, parent.bottom * scale,
                parent.x * scale, middle * scale,
                child.x * scale, middle * scale,
                child.x * scale, child.y * scale,
                fill=colors['edge'], width=max(1, int(1.5 * scale)))

        title_size = max(8, int(13 * scale))
        argument_size = max(7, int(11 * scale))

        for node in self.layout.nodes:
            box = self.canvas.create_rectangle(
                node.left * scale, node.y * scale, node.right * scale, node.bottom * scale,
                fill=colors[f'{node.kind}_fill'], outline=colors[f'{node.kind}_border'],
                width=max(1, int(1.5 * scale)))
            self._items[box] = node

            title = f'{node.marker} {node.label}' if node.marker else node.label
            label = self.canvas.create_text(
                node.x * scale, (node.y + graph_module.TITLE_HEIGHT / 2 + 3) * scale,
                text=title, fill=colors['text'], font=('Arial', title_size, 'bold'))
            self._items[label] = node

            offset = node.y + graph_module.TITLE_HEIGHT + 8
            for line in node.argument_lines:
                item = self.canvas.create_text(
                    (node.left + graph_module.PADDING) * scale, offset * scale,
                    text=line, anchor='w', fill=colors['subtext'],
                    font=('Arial', argument_size))
                self._items[item] = node
                offset += graph_module.ARGUMENT_HEIGHT

        self._draw_legend(colors, scale, title_size, argument_size)
        self.canvas.configure(scrollregion=(0, 0, self.layout.width * scale,
                                            self.layout.height * scale))

    def _draw_legend(self, colors, scale, title_size, argument_size):
        """The legend under the tree: what each colour and symbol stands for."""
        if not self.layout.legend:
            return
        self.canvas.create_text(
            graph_module.MARGIN * scale,
            (self.layout.legend_title_y + graph_module.LEGEND_TITLE_HEIGHT / 2) * scale,
            text='Legend', anchor='w', fill=colors['subtext'],
            font=('Arial', title_size, 'bold'))
        for row in self.layout.legend:
            middle = (row.y + graph_module.SWATCH_HEIGHT / 2) * scale
            self.canvas.create_rectangle(
                row.x * scale, row.y * scale,
                (row.x + graph_module.SWATCH_WIDTH) * scale,
                (row.y + graph_module.SWATCH_HEIGHT) * scale,
                fill=colors[f'{row.kind}_fill'], outline=colors[f'{row.kind}_border'],
                width=max(1, int(1.5 * scale)))
            marker = graph_module.MARKERS.get(row.kind, '')
            if marker:
                self.canvas.create_text(
                    (row.x + graph_module.SWATCH_WIDTH / 2) * scale, middle, text=marker,
                    fill=colors['text'], font=('Arial', title_size, 'bold'))
            self.canvas.create_text(row.name_x * scale, middle, text=row.name, anchor='w',
                                    fill=colors['text'], font=('Arial', title_size, 'bold'))
            self.canvas.create_text(row.description_x * scale, middle, text=row.description,
                                    anchor='w', fill=colors['subtext'],
                                    font=('Arial', argument_size))
