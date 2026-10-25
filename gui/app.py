"""The pipeline window.

Left to right it follows the run: the scene on the left, the command and the six
module panels in the middle, and on the right the tree itself - as a graph, as code,
and as the list of checks it had to pass. The log of every module runs along the
bottom.

Nothing blocks the window: a run happens on a worker thread and each module reports
back as it finishes, so the panels fill in one by one while it is still going.
"""

import json
import os
import threading

import customtkinter
from PIL import Image

import config
from core import logging_setup
from core.pipeline import Check, Pipeline, StageResult, StageStatus
from core.run_context import RunContext
from gui.graph_view import GraphView
from gui.log_view import LogView
from gui.stage_panel import CheckTable, StagePanel, open_path
from modules import graph as graph_module
from modules import loop
from modules.command import CommandStage
from modules.enrichment import EnrichmentStage
from modules.graph import TreeGraphStage
from modules.loop_stage import GenerationLoopStage
from modules.scene import SceneStage, load_scene

MONOSPACE = ('Menlo', 11) if os.name != 'nt' else ('Consolas', 11)
SCENE_IMAGE_WIDTH = 380

# The two conditions the pipeline can run in.
JUDGE_MODE = 'Judge'
BASELINE_MODE = 'Baseline'

log = logging_setup.get_logger('gui')


class ScenePanel(customtkinter.CTkFrame):
    """The chosen scene: its photo, and the object list the generator will be shown."""

    def __init__(self, master, on_scene_change):
        super().__init__(master, corner_radius=8)
        self.on_scene_change = on_scene_change
        self.scene = None
        self._image = None  # kept so Tk does not discard it

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        customtkinter.CTkLabel(self, text='Scene', font=('Arial', 15, 'bold')).grid(
            row=0, column=0, padx=14, pady=(12, 4), sticky='w')

        self.menu = customtkinter.CTkOptionMenu(
            self, values=config.SCENES, command=self.select)
        self.menu.grid(row=1, column=0, padx=14, pady=4, sticky='ew')
        self.menu.set('Choose a scene')

        self.image_label = customtkinter.CTkLabel(self, text='No scene selected',
                                                  text_color='gray55')
        self.image_label.grid(row=2, column=0, padx=14, pady=8)

        customtkinter.CTkLabel(self, text='Objects the generator sees', anchor='w',
                               text_color='gray60', font=('Arial', 11)).grid(
            row=3, column=0, padx=14, pady=(4, 0), sticky='sw')

        self.objects_box = customtkinter.CTkTextbox(self, wrap='none', font=MONOSPACE,
                                                    height=210)
        self.objects_box.grid(row=4, column=0, padx=14, pady=(4, 14), sticky='nsew')
        self.objects_box.configure(state='disabled')

    def select(self, scene_number):
        self.scene = scene_number
        try:
            scene = load_scene(scene_number)
        except Exception as error:  # noqa: BLE001 - shown in the panel instead
            self._set_objects(str(error))
            log.error('could not load %s: %s', scene_number, error)
            return

        if scene.image_path:
            image = Image.open(scene.image_path)
            height = round(image.height * SCENE_IMAGE_WIDTH / image.width)
            self._image = customtkinter.CTkImage(light_image=image, dark_image=image,
                                                 size=(SCENE_IMAGE_WIDTH, height))
            self.image_label.configure(image=self._image, text='')
        else:
            self.image_label.configure(image=None, text=f'No photo for {scene_number}')

        self._set_objects(scene.objects_block())
        log.info('scene %s selected: %d objects', scene_number, len(scene.objects))
        self.on_scene_change(scene_number)

    def _set_objects(self, text):
        self.objects_box.configure(state='normal')
        self.objects_box.delete('1.0', 'end')
        self.objects_box.insert('1.0', text)
        self.objects_box.configure(state='disabled')


class App(customtkinter.CTk):
    """The window, and the controller that runs the pipeline behind it."""

    def __init__(self):
        super().__init__()
        self.title('Natural command → Behavior tree')
        self.geometry('1680x1020')
        self.minsize(1380, 860)

        self.stages = [SceneStage(), CommandStage(), EnrichmentStage(),
                       GenerationLoopStage(), TreeGraphStage()]
        self.pipeline = Pipeline(self.stages, on_update=self._stage_updated)
        self.panels = {}
        self.context = None
        self.running = False
        self._attempts = []        # the attempts of the run on screen
        self._payload_png = None   # the saved image of the accepted tree
        self._judged = True        # False when the run on screen was a baseline

        self.grid_columnconfigure(0, weight=0, minsize=420)
        self.grid_columnconfigure(1, weight=3, minsize=480)
        self.grid_columnconfigure(2, weight=4, minsize=460)
        self.grid_rowconfigure(1, weight=3)
        self.grid_rowconfigure(2, weight=1)

        self._build_header()
        self._build_scene_column()
        self._build_pipeline_column()
        self._build_output_column()

        self.log_view = LogView(self, corner_radius=8)
        self.log_view.grid(row=2, column=0, columnspan=3, sticky='nsew',
                           padx=16, pady=(0, 12))

        self.status('Choose a scene, type a command, then run the pipeline.')
        log.info('interface ready')

    # --- Layout ---------------------------------------------------------

    def _build_header(self):
        header = customtkinter.CTkFrame(self, fg_color='transparent')
        header.grid(row=0, column=0, columnspan=3, sticky='ew', padx=16, pady=(14, 8))
        header.grid_columnconfigure(1, weight=1)

        customtkinter.CTkLabel(
            header, text='Scene  →  Command  →  Scene-aware command  →  '
                         'Behavior tree  →  Syntax check  →  Graph',
            font=('Arial', 17, 'bold')).grid(row=0, column=0, sticky='w')

        self.status_label = customtkinter.CTkLabel(
            header, text='', anchor='e', text_color='gray60', font=('Arial', 12))
        self.status_label.grid(row=0, column=1, sticky='ew', padx=16)

        self.run_menu = customtkinter.CTkOptionMenu(
            header, values=['current run'], width=210, command=self.open_run)
        self.run_menu.grid(row=0, column=2, padx=(0, 8))
        self.run_menu.set('current run')

        self.folder_button = customtkinter.CTkButton(
            header, text='Run folder', width=100, fg_color='#2b3a4a',
            hover_color='#36506b', state='disabled',
            command=lambda: open_path(self.context.directory) if self.context else None)
        self.folder_button.grid(row=0, column=3)

    def _build_scene_column(self):
        self.scene_panel = ScenePanel(self, on_scene_change=self._scene_changed)
        self.scene_panel.grid(row=1, column=0, sticky='nsew', padx=(16, 8), pady=(0, 8))

    def _build_pipeline_column(self):
        column = customtkinter.CTkFrame(self, fg_color='transparent')
        column.grid(row=1, column=1, sticky='nsew', padx=8, pady=(0, 8))
        column.grid_columnconfigure(0, weight=1)
        column.grid_rowconfigure(1, weight=1)

        # The command and the run controls.
        box = customtkinter.CTkFrame(column, corner_radius=8)
        box.grid(row=0, column=0, sticky='ew', pady=(0, 8))
        box.grid_columnconfigure(0, weight=1)

        customtkinter.CTkLabel(box, text='Natural-language command',
                               font=('Arial', 15, 'bold')).grid(
            row=0, column=0, columnspan=3, padx=14, pady=(12, 4), sticky='w')

        self.command_box = customtkinter.CTkTextbox(box, height=68, wrap='word',
                                                    font=('Arial', 13))
        self.command_box.grid(row=1, column=0, columnspan=3, padx=14, pady=(0, 8),
                              sticky='ew')

        switches = customtkinter.CTkFrame(box, fg_color='transparent')
        switches.grid(row=2, column=0, padx=14, pady=(0, 12), sticky='w')

        self.enrich_switch = customtkinter.CTkSwitch(
            switches, text='Enrich with the scene first', font=('Arial', 11))
        self.enrich_switch.select()
        self.enrich_switch.grid(row=0, column=0, sticky='w')

        # Judge: the loop repairs a rejected tree. Baseline: one tree, not judged.
        self.mode_selector = customtkinter.CTkSegmentedButton(
            switches, values=[JUDGE_MODE, BASELINE_MODE], font=('Arial', 11),
            command=self.mode_changed)
        self.mode_selector.set(JUDGE_MODE)
        self.mode_selector.grid(row=1, column=0, sticky='w', pady=(8, 0))

        models = customtkinter.CTkFrame(box, fg_color='transparent')
        models.grid(row=2, column=1, padx=6, pady=(0, 12), sticky='e')

        customtkinter.CTkLabel(models, text='tree', text_color='gray60',
                               font=('Arial', 10)).grid(row=0, column=0, padx=(0, 4))
        self.model_menu = customtkinter.CTkOptionMenu(
            models, values=config.AVAILABLE_MODELS, width=118, height=28,
            font=('Arial', 11), command=self.models_changed)
        self.model_menu.set(config.BT_GENERATION_MODEL)
        self.model_menu.grid(row=0, column=1)

        customtkinter.CTkLabel(models, text='judge', text_color='gray60',
                               font=('Arial', 10)).grid(row=0, column=2, padx=(10, 4))
        self.judge_menu = customtkinter.CTkOptionMenu(
            models, values=config.AVAILABLE_MODELS, width=118, height=28,
            font=('Arial', 11), command=self.models_changed)
        self.judge_menu.set(config.JUDGE_MODEL)
        self.judge_menu.grid(row=0, column=3)

        # The reasoning effort of each model. It only applies to a model that is called
        # through the Responses API, so the menu is greyed out for any other.
        customtkinter.CTkLabel(models, text='effort', text_color='gray60',
                               font=('Arial', 10)).grid(row=1, column=0, padx=(0, 4),
                                                        pady=(6, 0))
        self.effort_menu = customtkinter.CTkOptionMenu(
            models, values=config.REASONING_EFFORTS, width=118, height=28,
            font=('Arial', 11))
        self.effort_menu.set(config.BT_GENERATION_REASONING_EFFORT)
        self.effort_menu.grid(row=1, column=1, pady=(6, 0))

        customtkinter.CTkLabel(models, text='effort', text_color='gray60',
                               font=('Arial', 10)).grid(row=1, column=2, padx=(10, 4),
                                                        pady=(6, 0))
        self.judge_effort_menu = customtkinter.CTkOptionMenu(
            models, values=config.REASONING_EFFORTS, width=118, height=28,
            font=('Arial', 11))
        self.judge_effort_menu.set(config.JUDGE_REASONING_EFFORT)
        self.judge_effort_menu.grid(row=1, column=3, pady=(6, 0))
        self.models_changed()

        self.run_button = customtkinter.CTkButton(
            box, text='Run pipeline', width=140, height=34, font=('Arial', 13, 'bold'),
            command=self.run_pipeline)
        self.run_button.grid(row=2, column=2, padx=(6, 14), pady=(0, 12))

        # One panel per module.
        panels = customtkinter.CTkScrollableFrame(column, label_text='Pipeline modules',
                                                  corner_radius=8)
        panels.grid(row=1, column=0, sticky='nsew')
        panels.grid_columnconfigure(0, weight=1)
        for index, stage in enumerate(self.stages, start=1):
            panel = StagePanel(panels, stage, index)
            panel.grid(row=index, column=0, sticky='ew', padx=6, pady=4)
            self.panels[stage.name] = panel

    def _build_output_column(self):
        column = customtkinter.CTkFrame(self, fg_color='transparent')
        column.grid(row=1, column=2, sticky='nsew', padx=(8, 16), pady=(0, 8))
        column.grid_columnconfigure(0, weight=1)
        column.grid_rowconfigure(1, weight=1)

        # One run can hold several attempts; this picks which one is shown below.
        bar = customtkinter.CTkFrame(column, corner_radius=8)
        bar.grid(row=0, column=0, sticky='ew', pady=(0, 6))
        bar.grid_columnconfigure(1, weight=1)

        customtkinter.CTkLabel(bar, text='Attempt', font=('Arial', 12, 'bold')).grid(
            row=0, column=0, padx=(14, 8), pady=8)
        self.attempt_menu = customtkinter.CTkOptionMenu(
            bar, values=['—'], width=320, height=28, font=('Arial', 11),
            command=self.show_attempt)
        self.attempt_menu.grid(row=0, column=1, padx=(0, 14), pady=8, sticky='w')
        self.attempt_menu.configure(state='disabled')

        self.tabs = customtkinter.CTkTabview(column, corner_radius=8)
        self.tabs.grid(row=1, column=0, sticky='nsew')
        for name in ('Tree graph', 'Code', 'Checks', 'Judge'):
            self.tabs.add(name)
            self.tabs.tab(name).grid_columnconfigure(0, weight=1)
            self.tabs.tab(name).grid_rowconfigure(0, weight=1)

        self.graph_view = GraphView(self.tabs.tab('Tree graph'), fg_color='transparent')
        self.graph_view.grid(row=0, column=0, sticky='nsew')

        code_tab = self.tabs.tab('Code')
        self.code_box = customtkinter.CTkTextbox(code_tab, wrap='none', font=MONOSPACE)
        self.code_box.grid(row=0, column=0, sticky='nsew', padx=8, pady=8)
        self.code_box.configure(state='disabled')
        customtkinter.CTkButton(code_tab, text='Copy', width=80, height=26,
                                font=('Arial', 11), command=self.copy_code).grid(
            row=1, column=0, sticky='e', padx=8, pady=(0, 8))

        self.check_table = CheckTable(self.tabs.tab('Checks'), label_text='')
        self.check_table.grid(row=0, column=0, sticky='nsew', padx=4, pady=4)

        self.judge_box = customtkinter.CTkTextbox(
            self.tabs.tab('Judge'), wrap='word', font=MONOSPACE)
        self.judge_box.grid(row=0, column=0, sticky='nsew', padx=8, pady=8)
        self.judge_box.configure(state='disabled')

    # --- Running --------------------------------------------------------

    @property
    def judging(self):
        return self.mode_selector.get() == JUDGE_MODE

    def models_changed(self, _model=None):
        """Enable an effort menu only for a model that takes a reasoning effort."""
        takes_effort = config.RESPONSES_API_MODELS
        self.effort_menu.configure(
            state='normal' if self.model_menu.get() in takes_effort else 'disabled')
        self.judge_effort_menu.configure(
            state='normal' if self.judging and self.judge_menu.get() in takes_effort
            else 'disabled')

    def mode_changed(self, mode):
        """Grey out the judge model in baseline, and say what the run will do."""
        self.judge_menu.configure(state='normal' if self.judging else 'disabled')
        self.models_changed()
        if mode == JUDGE_MODE:
            self.status('Judge: a rejected tree is sent back for repair, up to three.')
        else:
            self.status('Baseline: one tree, checked but not judged, and no repairs.',
                        warn=True)

    def _scene_changed(self, scene_number):
        self.status(f'Scene {scene_number} loaded. Type a command and run the pipeline.')

    def run_pipeline(self):
        if self.running:
            return
        scene = self.scene_panel.scene
        command = self.command_box.get('1.0', 'end').strip()
        if not scene:
            self.status('Choose a scene first.', error=True)
            return
        if not command:
            self.status('Type a command first.', error=True)
            return

        selected = [stage.name for stage in self.stages]
        if not self.enrich_switch.get():
            selected.remove('enrichment')

        for panel in self.panels.values():
            panel.reset()
        if 'enrichment' not in selected:
            self.panels['enrichment'].set_result(StageResult(
                stage='enrichment', status=StageStatus.SKIPPED,
                summary='skipped — the command goes to the generator as typed'))
        self.graph_view.clear('Running…')
        self._set_code('')
        self.check_table.show([])

        self.context = RunContext(scene=scene)
        self.payload = {
            'scene': scene,
            'command': command,
            'generation_model': self.model_menu.get(),
            'judge_model': self.judge_menu.get(),
            'generation_reasoning_effort': self.effort_menu.get(),
            'judge_reasoning_effort': self.judge_effort_menu.get(),
            'enrichment_on': 'enrichment' in selected,
            'judge_enabled': self.judging,
        }
        self.running = True
        self.run_button.configure(state='disabled', text='Running…')
        self.folder_button.configure(state='normal')
        self.status(f'Run {self.context.run_id} started.')

        threading.Thread(target=self._run, args=(selected,), daemon=True).start()

    def _run(self, selected):
        """The worker thread: run the pipeline, then hand the results back."""
        try:
            self.pipeline.run(self.context, self.payload, stages=selected)
        except Exception as error:  # noqa: BLE001 - never lose the window to an error
            log.exception('the run failed outside a stage')
            self.after(0, lambda: self.status(f'The run failed: {error}', error=True))
        finally:
            self.after(0, self._run_finished)

    def _stage_updated(self, name, result):
        """Called from the worker thread as each module starts and finishes."""
        self.after(0, lambda: self._apply_stage(name, result))

    def _apply_stage(self, name, result):
        panel = self.panels.get(name)
        if panel:
            panel.set_result(result)
        if result.status == StageStatus.RUNNING:
            self.status(f'{self.pipeline.stage(name).title}…')

    def _run_finished(self):
        self.running = False
        self.run_button.configure(state='normal', text='Run pipeline')
        self._show_outputs(self.payload)
        self._refresh_runs()

        results = self.pipeline.results
        failed = [name for name, result in results.items()
                  if result.status in (StageStatus.FAILED, StageStatus.REJECTED)]
        record = self.payload.get('loop_record') or {}
        if failed:
            self.status(f'{self.pipeline.stage(failed[0]).title} — '
                        f'{results[failed[0]].summary}', error=True)
            if failed[0] == 'loop' and record.get('status') == 'failed_syntax_cap':
                self.tabs.set('Checks')
        elif record.get('status') == 'no_judge':
            self.status(f'Baseline: the tree was built and checked, but nothing judged '
                        f'it. Everything is in {self.context.directory.name}.')
        else:
            attempts = len(record.get('attempts', []))
            self.status(f'Accepted after {attempts} attempt'
                        f'{"s" if attempts != 1 else ""}. '
                        f'Everything is in {self.context.directory.name}.')

    # --- Showing one attempt --------------------------------------------

    def _show_outputs(self, payload):
        """Fill the attempt selector and show the one that decided the run."""
        record = payload.get('loop_record') or {}
        self._attempts = list(record.get('attempts', []))
        self._payload_png = payload.get('graph_png')
        self._judged = record.get('status') != 'no_judge'

        if not self._attempts:
            self.attempt_menu.configure(values=['—'], state='disabled')
            self.attempt_menu.set('—')
            self._set_code(payload.get('answer') or '')
            self.check_table.show([])
            self._set_judge('')
            self.graph_view.clear('No tree was generated.')
            return

        labels = [self._attempt_label(a) for a in self._attempts]
        self.attempt_menu.configure(values=labels, state='normal')
        self.attempt_menu.set(labels[-1])
        self.show_attempt(labels[-1])

    def _attempt_label(self, attempt):
        n = attempt['n']
        if attempt['kind'] == 'no_code':
            return f'{n} · no code in the reply'
        if attempt.get('syntax_passed') is False:
            return f'{n} · syntax failed'
        form = attempt.get('judge_form')
        if form is None:
            return f'{n} · not judged' if not self._judged else f'{n} · no judgement'
        return f'{n} · judge {form["verdict"]}ed'

    def show_attempt(self, label):
        """Switch the code, checks, judgement and graph to one attempt."""
        attempt = next((a for a in self._attempts
                        if self._attempt_label(a) == label), None)
        if attempt is None:
            return

        if attempt['kind'] == 'no_code':
            self._set_code(attempt.get('generator_reply') or '')
            self.check_table.show([])
            self._set_judge('The reply held no create_behavior_tree() code block, so '
                            'there was nothing to check or judge. It was sent back '
                            'asking for the tree.')
            self.graph_view.clear('This reply held no code, so no tree was built.')
            self.tabs.set('Code')
            return

        self._set_code(attempt.get('code') or '')
        self.check_table.show(attempt.get('checks', []))
        self._set_judge(self._judgement_text(attempt, self._judged))

        tree = attempt.get('tree')
        if tree is not None:
            layout = graph_module.layout(graph_module.from_py_trees(tree))
            accepted = attempt.get('judge_form', {}) or {}
            self.graph_view.show(
                layout,
                self._payload_png if accepted.get('verdict') == 'accept' else None)
            self.tabs.set('Tree graph')
        elif attempt.get('syntax_passed'):
            # A run reopened from disk: only the accepted tree is stored as a graph.
            self.graph_view.clear('This run was reopened from disk, which keeps the '
                                  'graph of the accepted tree only.')
        else:
            self.graph_view.clear('The syntax check did not pass, so no tree was built.')
            self.tabs.set('Checks')

    @staticmethod
    def _judgement_text(attempt, judged=True):
        form = attempt.get('judge_form')
        lines = []
        if form is None:
            if not judged:
                lines.append('Baseline run: the judge was switched off, so this tree '
                             'was built and checked but nothing decided whether it is '
                             'right.')
            elif attempt.get('syntax_passed') is False:
                lines.append('The syntax check failed, so the judge was never asked.')
            else:
                lines.append('The judge did not return a valid judgement form.')
            for index, raw in enumerate(attempt.get('judge_replies', []), start=1):
                lines += ['', f'Reply {index}:', raw]
        else:
            lines.append(f'Verdict: {form["verdict"]}')
            if form['errors']:
                lines.append('')
                lines.append('What is wrong:')
                lines += [f'  · {sentence}' for sentence in loop.form_sentences(form)]
            if form['reason']:
                lines += ['', 'Reason:', form['reason']]
        if attempt.get('outline'):
            lines += ['', 'The tree the judge was shown:', '', attempt['outline']]
        return '\n'.join(lines)

    def _set_judge(self, text):
        self.judge_box.configure(state='normal')
        self.judge_box.delete('1.0', 'end')
        self.judge_box.insert('1.0', text)
        self.judge_box.configure(state='disabled')

    # --- Past runs ------------------------------------------------------

    def _refresh_runs(self):
        runs = RunContext.existing_runs()[:40]
        self.run_menu.configure(values=['current run', *runs])
        self.run_menu.set('current run')

    def _load_stored_attempts(self, directory, summary):
        """Rebuild the attempt selector of a run that has already finished.

        Everything comes off disk: the code, the check report and the judgement form
        of each attempt. The built trees are not stored, so the graph of a past run
        comes from bt_graph.json - the accepted tree only.
        """
        loop_summary = summary.get('loop') or {}
        stored = loop_summary.get('attempts') or []
        self._attempts = []
        self._payload_png = directory / 'bt_graph.png'
        self._judged = loop_summary.get('status') != 'no_judge'

        for entry in stored:
            folder = directory / 'attempts' / f'{entry["n"]:02d}'
            attempt = dict(entry)
            code_file = folder / 'create_behavior_tree.py'
            if code_file.exists():
                attempt['code'] = code_file.read_text(encoding='utf-8')
            report = folder / 'tester_report.json'
            if report.exists():
                data = json.loads(report.read_text(encoding='utf-8'))
                attempt['checks'] = [Check(**c) for c in data.get('checks', [])]
            outline = folder / 'judge_outline.txt'
            if outline.exists():
                attempt['outline'] = outline.read_text(encoding='utf-8')
            self._attempts.append(attempt)

        if not self._attempts:
            self.attempt_menu.configure(values=['—'], state='disabled')
            self.attempt_menu.set('—')
            self._set_code('')
            self.check_table.show([])
            self._set_judge('')
            return

        labels = [self._attempt_label(a) for a in self._attempts]
        self.attempt_menu.configure(values=labels, state='normal')
        self.attempt_menu.set(labels[-1])
        self.show_attempt(labels[-1])

    def open_run(self, run_id):
        """Reopen a finished run from its directory."""
        if run_id == 'current run':
            return
        directory = config.RUNS_DIR / run_id
        summary_file = directory / 'summary.json'
        if not summary_file.exists():
            self.status(f'{run_id} has no summary.json.', error=True)
            return

        summary = json.loads(summary_file.read_text(encoding='utf-8'))
        self.context = RunContext.load(run_id)
        self.folder_button.configure(state='normal')

        for panel in self.panels.values():
            panel.reset()
        for name, payload in summary.get('stages', {}).items():
            result = StageResult.from_dict(payload)
            if name in self.panels:
                self.panels[name].set_result(result)

        self.command_box.delete('1.0', 'end')
        self.command_box.insert('1.0', summary.get('command') or '')
        if summary.get('scene'):
            self.scene_panel.menu.set(summary['scene'])
            self.scene_panel.select(summary['scene'])

        self._load_stored_attempts(directory, summary)

        graph_file = directory / 'bt_graph.json'
        if graph_file.exists():
            image = directory / 'bt_graph.png'
            self.graph_view.show_from_json(
                json.loads(graph_file.read_text(encoding='utf-8')),
                image if image.exists() else None)
            self.tabs.set('Tree graph')
        else:
            self.graph_view.clear('This run produced no tree.')

        self.status(f'Showing {run_id} ({summary.get("total_seconds", 0):.1f}s).')
        log.info('reopened run %s', run_id)

    # --- Small helpers --------------------------------------------------

    def _set_code(self, text):
        self.code_box.configure(state='normal')
        self.code_box.delete('1.0', 'end')
        self.code_box.insert('1.0', text)
        self.code_box.configure(state='disabled')

    def copy_code(self):
        text = self.code_box.get('1.0', 'end').strip()
        if text:
            self.clipboard_clear()
            self.clipboard_append(text)
            self.status('Copied to the clipboard.')

    def status(self, text, error=False, warn=False):
        colour = '#d9534f' if error else '#d5a05b' if warn else 'gray60'
        self.status_label.configure(text=text, text_color=colour)


def main():
    logging_setup.configure()
    customtkinter.set_appearance_mode('dark')
    customtkinter.set_default_color_theme('blue')
    App().mainloop()
