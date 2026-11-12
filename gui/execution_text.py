"""The Execution tab's text: an executor result as (text, style) lines.

Plain Python, without customtkinter, so it can be tested on its own. The style names are
the tags gui/execution_view.py colours.
"""

from modules import xml_tree

# The node types that act or check; the others (Sequence, Selector, decorators) only pass
# their children's status up.
LEAVES = set(xml_tree.LEAVES)


def execution_lines(result, attempt=None):
    """``[(text, style)]`` for one executor result: header, every tick, the final table."""
    lines = []
    lines += _header(result, attempt)
    previous = {}
    for entry in result['trace']:
        lines += _tick(entry, previous)
        previous = entry['blackboard']
    lines += _final_table(result)
    return lines


def last_failure(result):
    """What made the run fail, in one sentence; '' when nothing did."""
    if result.get('error'):
        return result['error']
    if result['status'] == 'INVALID':
        return '; '.join(result['check_errors'])
    if result['status'] != 'FAILURE' or not result['trace']:
        return ''
    failed = [node for node in result['trace'][-1]['visited']
              if node['status'] == 'FAILURE' and node['type'] in LEAVES]
    if not failed:
        return ''
    node = failed[-1]
    return f'{node["node"]} ({node["type"]}): {node["feedback"]}'


def _header(result, attempt):
    faults = result['final_table']['faults']
    title = f'Attempt {attempt}' if attempt is not None else 'Execution'
    lines = [(f'{title}: {result["status"]}', f'header_{result["status"]}'),
             (f'Stopped: {result["stopped"]}    Ticks: {result["ticks"]}    '
              f'Faults: {len(faults)}', 'plain')]
    failure = last_failure(result)
    lines.append((f'Last failure: {failure}' if failure else 'Last failure: none',
                  'FAILURE' if failure else 'muted'))
    for message in result['check_errors']:
        lines.append((f'  check: {message}', 'FAILURE'))
    lines.append(('', 'plain'))
    return lines


def _tick(entry, previous):
    lines = [(f'Tick {entry["tick"]}', 'title'), ('Nodes that ran', 'section')]
    for node in entry['visited']:
        feedback = f' — {node["feedback"]}' if node['feedback'] else ''
        lines.append((f'  [{node["status"]}] {node["node"]} ({node["type"]}){feedback}',
                      node['status'] if node['status'] in ('SUCCESS', 'FAILURE', 'RUNNING')
                      else 'plain'))

    lines.append(('Blackboard reads and writes', 'section'))
    for item in entry['activity']:
        style = 'write' if item['action'] == 'WRITE' else 'read'
        lines.append((f'  {item["action"]:<5} {item["key"]} = {_shown(item["value"])}   '
                      f'by {item["by"]}', style))
    if not entry['activity']:
        lines.append(('  (none)', 'muted'))

    lines.append(('Blackboard after the tick', 'section'))
    for key, value in entry['blackboard'].items():
        if key not in previous:
            lines.append((f'  {key} = {_shown(value)}   ← new', 'new'))
        elif previous[key] != value:
            lines.append((f'  {key} = {_shown(value)}   ← changed', 'changed'))
        else:
            lines.append((f'  {key} = {_shown(value)}', 'plain'))
    if not entry['blackboard']:
        lines.append(('  (empty)', 'muted'))

    lines.append(('World events', 'section'))
    for event in entry['events']:
        arguments = ', '.join(f'{name}={value}' for name, value in event['arguments'].items())
        text = f'  {event["action"]}({arguments})'
        if not event['action_happened']:
            lines.append((f'{text} REFUSED: {event["reason"]}', 'refused'))
        elif event['fault']:
            lines.append((f'{text} ok, fault {event["fault"]}: {event["reason"]}', 'fault'))
        else:
            lines.append((f'{text} ok', 'event_ok'))
    if not entry['events']:
        lines.append(('  (none)', 'muted'))
    lines.append(('', 'plain'))
    return lines


def _shown(value):
    """A trace value as the feedback shows it: a list of ids without quotes."""
    if isinstance(value, list):
        return '[' + ', '.join(_shown(item) for item in value) + ']'
    return str(value)


def _final_table(result):
    objects = result['final_table']['objects']
    lines = [('The table at the end', 'title'), ('Where the graspable objects are', 'section')]
    for obj in objects:
        if obj['graspable']:
            lines.append((f'  {obj["id"]}: {"on " + obj["on"] if obj["on"] else "on the table"}',
                          'plain'))

    lines.append(('Closed', 'section'))
    closed = [obj for obj in objects if obj['closed']]
    for obj in closed:
        lines.append((f'  {obj["id"]}, by {obj["closed_by"]}', 'plain'))
    if not closed:
        lines.append(('  nothing is closed', 'muted'))

    lines.append(('Liquids', 'section'))
    liquids = [obj for obj in objects if obj['holds_liquid']]
    for obj in liquids:
        lines.append((f'  {obj["id"]}: {obj["liquid_color"]}'
                      f'{" (spilled)" if obj["spilled"] else ""}', 'plain'))
    if not liquids:
        lines.append(('  nothing holds liquid', 'muted'))

    lines.append(('Faults', 'section'))
    for fault in result['final_table']['faults']:
        lines.append((f'  {fault["fault"]}: {fault["reason"]}', 'fault'))
    if not result['final_table']['faults']:
        lines.append(('  none', 'muted'))
    return lines
