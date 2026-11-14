"""Watch a behavior tree run on the mock world, tick by tick.

    python run_tree.py tree.xml --scene scene6             # any XML file on a scene
    python run_tree.py --run data/runs/<mode id>/<run id>  # a run's bt.xml, on its scene
    python run_tree.py --run data/runs/<run id>            # an old run, made before modes
    python run_tree.py --run <run id>                      # a run found by its id alone
    python run_tree.py tree.xml --scene scene6 --step      # pause after every tick (Enter)
    python run_tree.py tree.xml --scene scene6 --json out.json
"""

import argparse
import json
import sys
from pathlib import Path

import config
from core.pipeline import StageError
from core.run_context import RunContext
from modules.executor import execute, format_summary, format_tick, format_trace
from modules.mock_world import MockWorld
from modules.scene import load_scene


def read_arguments():
    parser = argparse.ArgumentParser(description='Watch a behavior tree run on the mock world.')
    parser.add_argument('tree', nargs='?', type=Path, help='an XML file; needs --scene')
    parser.add_argument('--scene', choices=config.SCENES, help='the scene to run it on')
    parser.add_argument('--run', metavar='RUN',
                        help="a run folder or a run id: its bt.xml, on that run's scene")
    parser.add_argument('--step', action='store_true', help='pause after every tick (Enter)')
    parser.add_argument('--json', type=Path, metavar='FILE', help='also save the full result')
    arguments = parser.parse_args()

    if arguments.run:
        if arguments.tree or arguments.scene:
            parser.error('--run takes the tree and the scene from the run; give neither')
        stored = RunContext.find(arguments.run)
        if stored is None:
            parser.error(f'there is no run {arguments.run} with a summary.json')
        arguments.tree = stored.directory / 'bt.xml'
        summary = stored.directory / 'summary.json'
        arguments.scene = json.loads(summary.read_text(encoding='utf-8'))['scene']
    elif not arguments.tree or not arguments.scene:
        parser.error('give an XML file with --scene, or --run with a run folder')
    if not arguments.tree.is_file():
        parser.error(f'{arguments.tree} does not exist')
    return arguments


def pause():
    try:
        input('Press Enter for the next tick ')
    except EOFError:        # no keyboard: just go on
        pass


def main():
    arguments = read_arguments()
    tree_xml = arguments.tree.read_text(encoding='utf-8')
    try:
        world = MockWorld.from_scene(load_scene(arguments.scene))
    except StageError as error:
        sys.exit(str(error))

    result = execute(tree_xml, world)
    colour = sys.stdout.isatty()           # red refusals and faults, but not in a file

    if arguments.step:
        for entry in result['trace']:
            print(format_tick(entry, colour) + '\n')
            pause()
        print(format_summary(result))
    else:
        print(format_trace(result, colour))
    if arguments.json:
        arguments.json.write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(f'\nSaved the full result to {arguments.json}')


if __name__ == '__main__':
    main()
