"""Running a behavior tree on a world, tick by tick, and recording what happened.

The result is plain JSON-ready data: for every tick, the nodes that ran, the blackboard's
reads and writes, the blackboard afterwards and the world's events. Nothing here decides
whether a run did the right thing.
"""

import py_trees

import config
from modules import bt_nodes, xml_tree
from modules.world import WorldObject

# The blackboard's first write to a key, and its reads, under the names the trace uses.
ACTIVITY_NAMES = {'INITIALISED': 'WRITE', 'ACCESSED': 'READ'}


def execute(tree_xml, world, max_ticks=None):
    """Check the XML, build it for this world, and tick it until it finishes.

    Returns {'status', 'stopped', 'ticks', 'trace', 'final_table', 'check_errors'}, and
    'error' when a node raised. status is SUCCESS, FAILURE or RUNNING (not finished at
    max_ticks), INVALID when the check failed and ERROR when a node raised. stopped is
    'finished', 'max_ticks', 'invalid' or 'error'.
    """
    checks, _, _ = xml_tree.check_xml(tree_xml)
    if not xml_tree.passed(checks):
        return _result('INVALID', 'invalid', [], world,
                       check_errors=[check.message for check in checks if check.blocking])

    # The blackboard is global in py_trees: without this, a run would see the last run's
    # values. clear() also deletes the activity stream, so it is enabled after.
    py_trees.blackboard.Blackboard.clear()
    py_trees.blackboard.Blackboard.enable_activity_stream()
    py_trees.blackboard.Blackboard.activity_stream.clear()

    root = xml_tree.build_tree(tree_xml, bt_nodes.registry(world))
    tree = py_trees.trees.BehaviourTree(root)
    snapshot = py_trees.visitors.SnapshotVisitor()
    tree.add_visitor(snapshot)
    nodes = {node.id: node for node in root.iterate()}

    limit = config.EXECUTION_MAX_TICKS if max_ticks is None else max_ticks
    trace = []
    for number in range(1, limit + 1):
        error = None
        try:
            tree.tick()
        except Exception as raised:  # noqa: BLE001 - a node's error ends the run, not the program
            error = f'{type(raised).__name__}: {raised}'
        trace.append(_tick_entry(number, snapshot.visited, nodes, world))
        if error:
            return _result('ERROR', 'error', trace, world, error=error)
        if root.status in (py_trees.common.Status.SUCCESS, py_trees.common.Status.FAILURE):
            return _result(root.status.name, 'finished', trace, world)
    return _result(root.status.name, 'max_ticks', trace, world)


def _result(status, stopped, trace, world, check_errors=(), error=None):
    result = {'status': status, 'stopped': stopped, 'ticks': len(trace), 'trace': trace,
              'final_table': world.snapshot(), 'check_errors': list(check_errors)}
    if error:
        result['error'] = error
    return result


def _tick_entry(number, visited, nodes, world):
    return {
        'tick': number,
        'visited': [{'node': _short(nodes[node_id].name),
                     'type': type(nodes[node_id]).__name__,
                     'status': status.name,
                     'feedback': nodes[node_id].feedback_message}
                    for node_id, status in visited.items()],
        'activity': _take_activity(),
        'blackboard': {key: _plain(value)
                       for key, value in sorted(py_trees.blackboard.Blackboard.storage.items())},
        'events': world.take_events(),
    }


def _take_activity():
    """The blackboard activity since the last call, then clear the stream."""
    stream = py_trees.blackboard.Blackboard.activity_stream
    activity = []
    for item in stream.data:
        entry = {'key': item.key,
                 'action': ACTIVITY_NAMES.get(item.activity_type, item.activity_type),
                 'by': _short(item.client_name),
                 'value': _plain(item.current_value)}
        if not activity or activity[-1] != entry:    # py_trees logs a port read twice
            activity.append(entry)
    stream.clear()
    return activity


def _short(name):
    """py_trees prefixes names with their parents (Root.ForEachX.Y); keep the XML name."""
    return str(name).rsplit('.', 1)[-1]


def _plain(value):
    """A blackboard value as JSON-ready data: an object is its id, a list a list of ids."""
    if isinstance(value, WorldObject):
        return value.id
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


# --- Printing -------------------------------------------------------------------------

RED, RESET = '\033[31m', '\033[0m'     # for a terminal that shows colours


def event_outcome(event):
    """How an event is shown: ('done' | 'done, FAULT: <fault>' | 'refused', reason)."""
    if not event['action_happened']:
        return 'refused', event['reason']
    if event['fault']:
        return f'done, FAULT: {event["fault"]}', event['reason']
    return 'done', event['reason']


def event_line(event, colour=False):
    """One world event as text: the action, done or refused, and the reason."""
    arguments = ', '.join(f'{name}={value}' for name, value in event['arguments'].items())
    outcome, reason = event_outcome(event)
    if colour and outcome != 'done':
        outcome = f'{RED}{outcome}{RESET}'
    return f'{event["action"]}({arguments}) {outcome}' + (f' — {reason}' if reason else '')

def format_trace(result, colour=False):
    """The result as plain text for a terminal: per tick, every node that ran with its
    status and feedback, every blackboard read and write, the world's events, and the
    blackboard afterwards; then the final status, where every graspable object ended up,
    and any faults. With colour, refusals and faults are red."""
    parts = [format_tick(entry, colour) for entry in result['trace']]
    parts.append(format_summary(result))
    return '\n\n'.join(parts)


def format_tick(entry, colour=False):
    """One tick of the trace as text. With colour, refusals and faults are red."""
    lines = [f'--- tick {entry["tick"]} ' + '-' * 60, 'Nodes that ran:']
    for node in entry['visited']:
        feedback = f': {node["feedback"]}' if node['feedback'] else ''
        lines.append(f'  [{node["status"]}] {node["node"]} ({node["type"]}){feedback}')
    lines.append('Blackboard reads and writes:')
    for item in entry['activity']:
        lines.append(f'  {item["action"]:<5} {item["key"]} = {item["value"]} by {item["by"]}')
    if not entry['activity']:
        lines.append('  (none)')
    lines.append('World events:')
    for event in entry['events']:
        lines.append('  ' + event_line(event, colour))
    if not entry['events']:
        lines.append('  (none)')
    lines.append('Blackboard afterwards:')
    for key, value in entry['blackboard'].items():
        lines.append(f'  {key} = {value}')
    if not entry['blackboard']:
        lines.append('  (empty)')
    return '\n'.join(lines)


def format_summary(result):
    """The final status, where every graspable object ended up, and any faults."""
    lines = ['=' * 70,
             f'Status: {result["status"]} (stopped: {result["stopped"]}, '
             f'ticks: {result["ticks"]})']
    if result.get('error'):
        lines.append(f'Error: {result["error"]}')
    for message in result['check_errors']:
        lines.append(f'Check error: {message}')
    lines.append('Where every graspable object ended up:')
    for obj in result['final_table']['objects']:
        if obj['graspable']:
            lines.append(f'  {obj["id"]}: {_where(obj)}')
    lines.append('Faults:')
    for fault in result['final_table']['faults']:
        lines.append(f'  {fault["fault"]}: {fault["reason"]}')
    if not result['final_table']['faults']:
        lines.append('  (none)')
    return '\n'.join(lines)


def _where(obj):
    parts = [f'on {obj["on"]}' if obj['on'] else 'on the table']
    if obj['closed']:
        parts.append(f'closed by {obj["closed_by"]}')
    if obj['holds_liquid']:
        parts.append(f'holds {obj["liquid_color"]} liquid')
    if obj['spilled']:
        parts.append('spilled')
    return ', '.join(parts)
