"""One panel per pipeline module: its state, its timing and everything it produced.

This is what makes a module trackable. The header is always visible - a coloured dot,
the module's name, what it did and how long it took. Opening the panel shows the
detail the stage reported and a button for every artifact it wrote, so the exact
prompt, the raw reply or the check report is one click away.
"""

import os
import platform
import subprocess

import customtkinter

from core.pipeline import StageStatus

MONOSPACE = ('Menlo', 11) if os.name != 'nt' else ('Consolas', 11)

# dot, colour and the word shown next to the module name.
STATUS_STYLE = {
    StageStatus.IDLE: ('○', '#7a7a7a', 'not run'),
    StageStatus.RUNNING: ('◐', '#d5a05b', 'running'),
    StageStatus.PASSED: ('●', '#6abf7b', 'passed'),
    StageStatus.FAILED: ('●', '#d9534f', 'failed'),
    StageStatus.REJECTED: ('●', '#d5a05b', 'declined'),
    StageStatus.SKIPPED: ('○', '#7a7a7a', 'skipped'),
}


def open_path(path):
    """Open a file or folder in the desktop's own viewer."""
    path = str(path)
    system = platform.system()
    try:
        if system == 'Darwin':
            subprocess.Popen(['open', path])
        elif system == 'Windows':
            os.startfile(path)  # noqa: S606 - the platform's own opener
        else:
            subprocess.Popen(['xdg-open', path])
    except OSError:
        pass


class StagePanel(customtkinter.CTkFrame):
    """The live view of one pipeline module."""

    def __init__(self, master, stage, index, on_run_from=None):
        super().__init__(master, corner_radius=8)
        self.stage = stage
        self.on_run_from = on_run_from
        self.expanded = False
        self.result = None

        self.grid_columnconfigure(1, weight=1)

        self.status_label = customtkinter.CTkLabel(
            self, text=STATUS_STYLE[StageStatus.IDLE][0], width=18,
            text_color=STATUS_STYLE[StageStatus.IDLE][1], font=('Arial', 16))
        self.status_label.grid(row=0, column=0, padx=(12, 4), pady=(10, 2))

        self.title_label = customtkinter.CTkLabel(
            self, text=f'{index} · {stage.title}', anchor='w', font=('Arial', 13, 'bold'))
        self.title_label.grid(row=0, column=1, sticky='w', pady=(10, 2))

        self.duration_label = customtkinter.CTkLabel(
            self, text='', anchor='e', width=60, text_color='gray60', font=('Arial', 11))
        self.duration_label.grid(row=0, column=2, padx=(4, 6), pady=(10, 2))

        self.toggle_button = customtkinter.CTkButton(
            self, text='Details', width=66, height=24, font=('Arial', 11),
            fg_color='transparent', border_width=1, border_color='gray40',
            command=self.toggle)
        self.toggle_button.grid(row=0, column=3, padx=(0, 10), pady=(10, 2))

        self.summary_label = customtkinter.CTkLabel(
            self, text=stage.description, anchor='w', justify='left',
            text_color='gray65', font=('Arial', 11), wraplength=430)
        self.summary_label.grid(row=1, column=1, columnspan=3, sticky='ew',
                                padx=(0, 12), pady=(0, 10))

        # The detail area, built once and shown only while expanded.
        self.detail_frame = customtkinter.CTkFrame(self, fg_color='#1e1e1e', corner_radius=6)
        self.detail_frame.grid_columnconfigure(0, weight=1)

        self.detail_box = customtkinter.CTkTextbox(
            self.detail_frame, height=150, wrap='word', font=MONOSPACE,
            fg_color='#1e1e1e', border_width=0)
        self.detail_box.grid(row=0, column=0, sticky='ew', padx=8, pady=(8, 4))
        self.detail_box.configure(state='disabled')

        self.artifact_frame = customtkinter.CTkFrame(self.detail_frame, fg_color='transparent')
        self.artifact_frame.grid(row=1, column=0, sticky='ew', padx=8, pady=(0, 8))

    # --- State ---------------------------------------------------------

    def set_result(self, result):
        """Show a new StageResult. Called on the UI thread."""
        self.result = result
        dot, colour, word = STATUS_STYLE.get(result.status, STATUS_STYLE[StageStatus.IDLE])
        self.status_label.configure(text=dot, text_color=colour)
        self.duration_label.configure(
            text=f'{result.duration_s:.2f}s' if result.duration_s else '')

        summary = result.summary or word
        self.summary_label.configure(
            text=summary,
            text_color={'failed': '#e08a86', 'rejected': '#e0bb86'}.get(
                result.status.value, 'gray65'))

        self._fill_detail(result)
        if result.status in (StageStatus.FAILED, StageStatus.REJECTED) and not self.expanded:
            self.toggle()  # a problem opens itself, so the reason is in front of you

    def reset(self):
        self.result = None
        dot, colour, _ = STATUS_STYLE[StageStatus.IDLE]
        self.status_label.configure(text=dot, text_color=colour)
        self.duration_label.configure(text='')
        self.summary_label.configure(text=self.stage.description, text_color='gray65')
        self._set_text('')
        for child in self.artifact_frame.winfo_children():
            child.destroy()
        if self.expanded:
            self.toggle()

    # --- Detail --------------------------------------------------------

    def _fill_detail(self, result):
        lines = []
        for key, value in result.detail.items():
            text = str(value)
            if '\n' in text:
                lines.append(f'{key}:')
                lines.extend(f'    {line}' for line in text.splitlines())
            else:
                lines.append(f'{key}: {text}')
        if result.error and result.error not in result.detail.values():
            lines.append('')
            lines.append('error:')
            lines.extend(f'    {line}' for line in str(result.error).splitlines())
        self._set_text('\n'.join(lines) or 'nothing reported')

        for child in self.artifact_frame.winfo_children():
            child.destroy()
        column = 0
        for label, path in result.artifacts.items():
            button = customtkinter.CTkButton(
                self.artifact_frame, text=label, height=22, font=('Arial', 10),
                fg_color='#2b3a4a', hover_color='#36506b',
                command=lambda p=path: open_path(p))
            button.grid(row=column // 3, column=column % 3, padx=3, pady=3, sticky='ew')
            self.artifact_frame.grid_columnconfigure(column % 3, weight=1)
            column += 1

    def _set_text(self, text):
        self.detail_box.configure(state='normal')
        self.detail_box.delete('1.0', 'end')
        self.detail_box.insert('1.0', text)
        self.detail_box.configure(state='disabled')

    def toggle(self):
        self.expanded = not self.expanded
        if self.expanded:
            self.detail_frame.grid(row=2, column=0, columnspan=4, sticky='ew',
                                   padx=10, pady=(0, 10))
            self.toggle_button.configure(text='Hide')
        else:
            self.detail_frame.grid_forget()
            self.toggle_button.configure(text='Details')


class CheckTable(customtkinter.CTkScrollableFrame):
    """The syntax tester's checks, one row each, grouped and colour coded."""

    COLOURS = {'pass': '#6abf7b', 'warn': '#d5a05b', 'fail': '#d9534f'}

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.grid_columnconfigure(1, weight=1)
        self.placeholder = customtkinter.CTkLabel(
            self, text='The checks appear here once the syntax check has run.',
            text_color='gray55', font=('Arial', 11))
        self.placeholder.grid(row=0, column=0, columnspan=3, padx=10, pady=14, sticky='w')

    def show(self, checks):
        for child in self.winfo_children():
            child.destroy()
        if not checks:
            customtkinter.CTkLabel(self, text='No checks were run.',
                                   text_color='gray55').grid(row=0, column=0, padx=10, pady=12)
            return

        row = 0
        group = None
        for check in checks:
            if check.group != group:
                group = check.group
                customtkinter.CTkLabel(
                    self, text=group.upper(), anchor='w', font=('Arial', 10, 'bold'),
                    text_color='gray55').grid(row=row, column=0, columnspan=3,
                                              sticky='w', padx=10, pady=(10, 2))
                row += 1

            if check.passed:
                mark, colour = '✓', self.COLOURS['pass']
            elif check.severity == 'warning':
                mark, colour = '!', self.COLOURS['warn']
            else:
                mark, colour = '✗', self.COLOURS['fail']

            customtkinter.CTkLabel(self, text=mark, text_color=colour, width=16,
                                   font=('Arial', 13, 'bold')).grid(
                row=row, column=0, padx=(12, 4), sticky='n')

            text = check.title
            if check.line:
                text += f'  (line {check.line})'
            customtkinter.CTkLabel(self, text=text, anchor='w', justify='left',
                                   font=('Arial', 12), wraplength=420).grid(
                row=row, column=1, sticky='w')
            row += 1

            if check.message:
                customtkinter.CTkLabel(
                    self, text=check.message, anchor='w', justify='left',
                    font=MONOSPACE, wraplength=420,
                    text_color='gray60' if check.passed else colour).grid(
                    row=row, column=1, sticky='w', pady=(0, 4))
                row += 1
