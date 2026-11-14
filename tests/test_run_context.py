"""Runs are saved in their mode's folder, and old flat runs are still listed and found.

    ../contextual-asr/venv/bin/python -m pytest tests -q
"""

import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from core.pipeline import StageError  # noqa: E402
from core.run_context import RunContext, mode_of_summary  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def runs(monkeypatch, tmp_path):
    monkeypatch.setattr(config, 'RUNS_DIR', tmp_path / 'runs')
    return tmp_path / 'runs'


def old_run(runs, run_id, loop):
    folder = runs / run_id
    folder.mkdir(parents=True)
    (folder / 'summary.json').write_text(json.dumps({'scene': 'scene6', 'loop': loop}))
    return folder


def test_a_new_run_is_written_in_its_mode_folder(runs):
    context = RunContext(scene='scene8', mode='dynamic_creator')
    assert context.directory == runs / 'dynamic_creator' / context.run_id
    assert context.directory.is_dir()
    readme = (runs / 'dynamic_creator' / 'README.txt').read_text()
    assert 'Dynamic creator' in readme and 'modes/dynamic_creator/README.md' in readme


def test_the_default_mode_and_an_unknown_one(runs):
    assert RunContext(scene='scene8').directory.parent == runs / config.DEFAULT_MODE
    with pytest.raises(StageError):
        RunContext(scene='scene8', mode='baseline')


def test_old_runs_are_listed_with_the_mode_they_were_made_in(runs):
    old_run(runs, '2026-10-01_10-00-00_aaaa', {'judge_enabled': False})
    old_run(runs, '2026-10-01_11-00-00_bbbb', {'judge_enabled': True})
    old_run(runs, '2026-10-01_12-00-00_cccc', {'status': 'accepted'})
    (runs / 'not_a_run').mkdir()
    new = RunContext(scene='scene8', mode='static_creator')
    (new.directory / 'summary.json').write_text('{}')

    listed = {run.run_id: run for run in RunContext.existing_runs()}
    assert set(listed) == {'2026-10-01_10-00-00_aaaa', '2026-10-01_11-00-00_bbbb',
                           '2026-10-01_12-00-00_cccc', new.run_id}
    first = listed['2026-10-01_10-00-00_aaaa']
    assert (first.mode, first.old) == ('static_creator', True)
    assert first.mode_title == 'Static creator (old run)'
    second = listed['2026-10-01_11-00-00_bbbb']
    assert (second.mode, second.old) == ('static_creator_dynamic_judge', True)
    assert second.mode_title == 'Static creator & Dynamic judge (old run)'
    assert listed['2026-10-01_12-00-00_cccc'].mode == 'static_creator_dynamic_judge'
    assert (listed[new.run_id].mode, listed[new.run_id].old) == ('static_creator', False)
    assert listed[new.run_id].label == f'{new.run_id} · Static creator'
    assert [run.run_id for run in RunContext.existing_runs()][0] == new.run_id


def test_a_run_is_found_by_its_id_or_its_folder(runs):
    folder = old_run(runs, '2026-10-01_10-00-00_aaaa', {'judge_enabled': False})
    new = RunContext(scene='scene8', mode='dynamic_creator')
    (new.directory / 'summary.json').write_text(json.dumps({'scene': 'scene8'}))

    assert RunContext.find('2026-10-01_10-00-00_aaaa').directory == folder
    assert RunContext.find(str(folder)).old
    assert RunContext.find(new.run_id).directory == new.directory
    assert not RunContext.find(str(new.directory)).old
    assert RunContext.find('2020-01-01_00-00-00_0000') is None

    loaded = RunContext.load(new.run_id)
    assert (loaded.directory, loaded.mode, loaded.scene) == (
        new.directory, 'dynamic_creator', 'scene8')
    assert RunContext.load(folder).directory == folder


def test_the_mode_of_a_summary():
    assert mode_of_summary({'loop': {'mode': {'id': 'dynamic_creator'}}}) == 'dynamic_creator'
    assert mode_of_summary({'mode': 'static_creator', 'loop': None}) == 'static_creator'
    assert mode_of_summary({'loop': {'judge_enabled': False}}) == 'static_creator'
    assert mode_of_summary({}) == 'static_creator_dynamic_judge'


def test_run_tree_opens_a_run_in_a_mode_folder(tmp_path):
    """run_tree.py --run with the path of a run inside a mode folder."""
    folder = tmp_path / 'static_creator' / '2026-10-01_10-00-00_aaaa'
    folder.mkdir(parents=True)
    (folder / 'summary.json').write_text(json.dumps({'scene': 'scene8'}))
    (folder / 'bt.xml').write_text(
        '<root main_tree_to_execute="MainTree"><BehaviorTree ID="MainTree">'
        '<Sequence name="Root" memory="true">'
        '<FindOne name="FindTube" key="tube" type="test tube"/>'
        '</Sequence></BehaviorTree></root>')
    done = subprocess.run([sys.executable, 'run_tree.py', '--run', str(folder)], cwd=ROOT,
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert 'SUCCESS' in done.stdout
