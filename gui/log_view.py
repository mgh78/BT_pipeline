"""The live log pane: every module's output as it happens, filterable.

Log records arrive from whichever thread the pipeline is running on, so they are
buffered and drained on the UI thread by a periodic poll.
"""

import os
import queue

import customtkinter

import config
from core import logging_setup
from gui.stage_panel import open_path

MONOSPACE = ('Menlo', 11) if os.name != 'nt' else ('Consolas', 11)

LEVEL_COLOURS = {
    'DEBUG': 'gray50',
    'INFO': '#cfcfcf',
    'WARNING': '#d5a05b',
    'ERROR': '#d9534f',
    'CRITICAL': '#d9534f',
}


class LogView(customtkinter.CTkFrame):
    """Shows the log of the current run, filtered by module and by level."""

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.queue = queue.SimpleQueue()
        self.module_filter = 'all'
        self.level_filter = 'INFO'

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        bar = customtkinter.CTkFrame(self, fg_color='transparent')
        bar.grid(row=0, column=0, sticky='ew', padx=8, pady=(8, 2))

        customtkinter.CTkLabel(bar, text='Log', font=('Arial', 13, 'bold')).pack(
            side='left', padx=(2, 12))

        self.module_menu = customtkinter.CTkOptionMenu(
            bar, values=['all', *logging_setup.MODULES], width=120, height=26,
            font=('Arial', 11), command=self._set_module)
        self.module_menu.set('all')
        self.module_menu.pack(side='left', padx=4)

        self.level_menu = customtkinter.CTkOptionMenu(
            bar, values=['DEBUG', 'INFO', 'WARNING', 'ERROR'], width=100, height=26,
            font=('Arial', 11), command=self._set_level)
        self.level_menu.set('INFO')
        self.level_menu.pack(side='left', padx=4)

        customtkinter.CTkButton(bar, text='Clear', width=60, height=26, font=('Arial', 11),
                                fg_color='transparent', border_width=1,
                                border_color='gray40', command=self.clear).pack(
            side='right', padx=(4, 2))
        customtkinter.CTkButton(bar, text='Log folder', width=90, height=26,
                                font=('Arial', 11), fg_color='#2b3a4a',
                                hover_color='#36506b',
                                command=lambda: open_path(config.LOG_DIR)).pack(side='right')

        self.textbox = customtkinter.CTkTextbox(
            self, wrap='none', font=MONOSPACE, fg_color='#141414', border_width=0)
        self.textbox.grid(row=1, column=0, sticky='nsew', padx=8, pady=(2, 8))
        self.textbox.configure(state='disabled')
        for level, colour in LEVEL_COLOURS.items():
            self.textbox.tag_config(level, foreground=colour)

        logging_setup.gui_buffer.subscribe(self.queue.put)
        self._drain()

    # --- Filters --------------------------------------------------------

    def _set_module(self, value):
        self.module_filter = value
        self._rebuild()

    def _set_level(self, value):
        self.level_filter = value
        self._rebuild()

    def _passes(self, entry):
        if self.module_filter != 'all' and entry['module'] != self.module_filter:
            return False
        order = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
        try:
            return order.index(entry['level']) >= order.index(self.level_filter)
        except ValueError:
            return True

    # --- Writing --------------------------------------------------------

    def _format(self, entry):
        return (f'{entry["ts"]}  {entry["level"][:4]:4}  {entry["module"]:<10}  '
                f'{entry["message"]}\n')

    def _append(self, entry):
        self.textbox.configure(state='normal')
        self.textbox.insert('end', self._format(entry), entry['level'])
        self.textbox.see('end')
        self.textbox.configure(state='disabled')

    def _rebuild(self):
        self.textbox.configure(state='normal')
        self.textbox.delete('1.0', 'end')
        for entry in logging_setup.gui_buffer.records:
            if self._passes(entry):
                self.textbox.insert('end', self._format(entry), entry['level'])
        self.textbox.see('end')
        self.textbox.configure(state='disabled')

    def clear(self):
        self.textbox.configure(state='normal')
        self.textbox.delete('1.0', 'end')
        self.textbox.configure(state='disabled')

    def _drain(self):
        """Move records from the logging thread onto the UI thread."""
        try:
            while True:
                entry = self.queue.get_nowait()
                if self._passes(entry):
                    self._append(entry)
        except queue.Empty:
            pass
        self.after(150, self._drain)
