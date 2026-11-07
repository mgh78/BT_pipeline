"""The Execution tab: run the chosen attempt's tree on the mock world, and show all of it.

Every click builds a fresh mock world from the run's scene and calls
modules/executor.py: execute(). The whole result is shown at once, read-only: a header,
every tick, and the table at the end (see gui/execution_text.py).
"""

import os

import customtkinter

from gui.execution_text import execution_lines
from modules.executor import execute
from modules.mock_world import MockWorld
from modules.scene import load_scene

MONOSPACE = ('Menlo', 11) if os.name != 'nt' else ('Consolas', 11)
FAMILY = MONOSPACE[0]

# style: tag options. Fonts go on the inner Tk text, which CTkTextbox allows for tags.
STYLES = {
    'header_SUCCESS': {'foreground': '#6abf7b', 'font': (FAMILY, 14, 'bold')},
    'header_FAILURE': {'foreground': '#d9534f', 'font': (FAMILY, 14, 'bold')},
    'header_RUNNING': {'foreground': '#d5a05b', 'font': (FAMILY, 14, 'bold')},
    'header_ERROR': {'foreground': '#d9534f', 'font': (FAMILY, 14, 'bold')},
    'header_INVALID': {'foreground': '#d9534f', 'font': (FAMILY, 14, 'bold')},
    'title': {'foreground': '#f2f2f2', 'font': (FAMILY, 12, 'bold'), 'spacing1': 6},
    'section': {'foreground': '#5b9bd5', 'font': (FAMILY, 11, 'bold')},
    'SUCCESS': {'foreground': '#6abf7b'},
    'FAILURE': {'foreground': '#d9534f'},
    'RUNNING': {'foreground': '#d5a05b'},
    'write': {'foreground': '#f2f2f2', 'font': (FAMILY, 11, 'bold')},
    'read': {'foreground': '#b9b9b9'},
    'new': {'foreground': '#6abf7b', 'background': '#1f3326'},
    'changed': {'foreground': '#e8c06a', 'background': '#3a3320'},
    'event_ok': {'foreground': '#cfcfcf'},
    'refused': {'foreground': '#d9534f'},
    'fault': {'foreground': '#d5a05b'},
    'muted': {'foreground': 'gray50'},
    'plain': {'foreground': '#cfcfcf'},
}


class ExecutionView(customtkinter.CTkFrame):
    """A Run tree button, the reason it is off, and the read-only execution text."""

    def __init__(self, master, on_status=None, **kwargs):
        super().__init__(master, **kwargs)
        self.on_status = on_status or (lambda *_args, **_kwargs: None)
        self._xml = None
        self._scene = None
        self._attempt = None

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        bar = customtkinter.CTkFrame(self, fg_color='transparent')
        bar.grid(row=0, column=0, sticky='ew', padx=8, pady=(8, 4))
        bar.grid_columnconfigure(1, weight=1)
        self.run_button = customtkinter.CTkButton(
            bar, text='Run tree', width=110, height=28, font=('Arial', 12, 'bold'),
            command=self.run, state='disabled')
        self.run_button.grid(row=0, column=0, sticky='w')
        self.reason_label = customtkinter.CTkLabel(
            bar, text='No attempt to run.', anchor='w', text_color='gray60',
            font=('Arial', 11))
        self.reason_label.grid(row=0, column=1, sticky='ew', padx=10)

        self.textbox = customtkinter.CTkTextbox(self, wrap='none', font=MONOSPACE)
        self.textbox.grid(row=1, column=0, sticky='nsew', padx=8, pady=(4, 8))
        for style, options in STYLES.items():
            self.textbox._textbox.tag_config(style, **options)
        self.textbox.configure(state='disabled')

    def set_attempt(self, attempt, scene):
        """Show which attempt Run tree will run, or why it cannot; clear the old result."""
        self._clear()
        self._attempt, self._scene = attempt, scene
        self._xml = attempt.get('code') if attempt and attempt['kind'] != 'no_code' else None
        if attempt is None:
            self._disable('No attempt to run.')
        elif not self._xml:
            self._disable(f'Attempt {attempt["n"]} has no XML tree.')
        elif attempt.get('syntax_passed') is not True:
            self._disable(f'Attempt {attempt["n"]} did not pass the syntax check.')
        elif not scene:
            self._disable('The run has no scene to run the tree on.')
        else:
            self.run_button.configure(state='normal')
            self.reason_label.configure(
                text=f'Runs attempt {attempt["n"]} on a fresh mock world of {scene}.',
                text_color='gray60')

    def unavailable(self, reason):
        """Turn the button off while something else is going on, such as a pipeline run."""
        self._clear()
        self._disable(reason)

    def run(self):
        if not self._xml:
            return
        try:
            world = MockWorld.from_scene(load_scene(self._scene))
            result = execute(self._xml, world)
        except Exception as error:  # noqa: BLE001 - shown in the tab instead
            self._show([(f'The tree could not be run: {type(error).__name__}: {error}',
                         'FAILURE')])
            self.on_status(f'Running attempt {self._attempt["n"]} failed: {error}', error=True)
            return
        self._show(execution_lines(result, self._attempt['n']))
        self.on_status(f'Attempt {self._attempt["n"]} ran on the mock world of {self._scene}: '
                       f'{result["status"]} after {result["ticks"]} tick(s).',
                       error=result['status'] != 'SUCCESS')

    def _disable(self, reason):
        self.run_button.configure(state='disabled')
        self.reason_label.configure(text=reason, text_color='#d5a05b')

    def _clear(self):
        self._show([])

    def _show(self, lines):
        self.textbox.configure(state='normal')
        self.textbox.delete('1.0', 'end')
        for text, style in lines:
            self.textbox._textbox.insert('end', text + '\n', style)
        self.textbox.configure(state='disabled')
        self.textbox.see('1.0')
