"""Stage 5 - the syntax tester.

This stage decides whether the tree the generator wrote is well formed. The generator
writes the tree as XML (see ``modes/static_creator/creator_prompt.txt``); the checks
themselves live in ``modules/xml_tree.py``. Nothing is executed on the robot: the only
thing run is the py_trees XML parser, which builds the tree from the stand-in nodes of
``modules/bt_nodes.py`` - the only way to prove the document really is a tree.

The checks are grouped, and each one reports on its own so a failure points at a line:

Syntax     - the reply is well-formed XML, inside the <root> and <BehaviorTree ID="MainTree">
             frame, with nothing but tags between the tags.
Structure  - the ``Root`` sequence, memory="true", only the tags the prompt allows, the
             right number of children per node, unique names, and an ``Inverter`` only
             around a condition (``HasProperty`` or ``HasCount``).
Arguments  - each node gets exactly the attributes it takes, counts such as ``times``
             are whole numbers, and every name is made of letters and digits.
Objects    - find nodes describe objects with properties the robot perceives, every
             object argument is a {key} that a find node (or a ForEach) stored earlier,
             and every key is used the way it was stored: a HasCount counts the list of a
             FindAll, by its plain key. Find nodes may stand anywhere in the tree, as long
             as each key is stored before it is used.
Build      - the py_trees XML parser builds the tree. Only run when nothing above failed.

A check marked ``warning`` is reported but does not stop the run; only a failed
``error`` check does.
"""

from core.pipeline import Stage, StageError, StageStatus
from modules import xml_tree


class SyntaxTestStage(Stage):
    """Check the generated XML tree, then prove py_trees builds it."""

    name = 'tester'
    title = 'Syntax check'
    description = 'Read and check the generated XML tree. Nothing is executed on the robot.'

    def check(self, tree_xml):
        """Run every check against one XML tree.

        Returns ``(checks, built_tree_or_None, root_element_or_None)``. This is what the
        generation loop calls for each attempt; :meth:`execute` wraps it so the stage
        still works on its own.
        """
        return xml_tree.check_xml(tree_xml)

    @staticmethod
    def passed(checks):
        """True when no blocking check failed. Warnings never stop a run."""
        return xml_tree.passed(checks)

    def execute(self, context, payload):
        tree_xml = payload.get('code')
        if not tree_xml:
            raise StageError('There is no generated tree to check.')

        checks, built, root = self.check(tree_xml)
        return self._report(context, payload, checks, built=built, root=root)

    # --- Reporting -------------------------------------------------------

    def _report(self, context, payload, checks, built, root=None):
        blocking = [c for c in checks if c.blocking]
        warnings = [c for c in checks if not c.passed and c.severity == 'warning']
        passed = [c for c in checks if c.passed]

        for check in checks:
            line = f' (line {check.line})' if check.line else ''
            if check.passed:
                self.log.debug('PASS  %-28s %s%s', check.id, check.message, line)
            elif check.severity == 'warning':
                self.log.warning('WARN  %-28s %s%s', check.id, check.message, line)
            else:
                self.log.error('FAIL  %-28s %s%s', check.id, check.message, line)

        payload['checks'] = checks
        payload['tree'] = built
        if built is not None:
            payload['tree_text'] = _as_text(built)

        artifacts = {'check report': context.write_json('tester_report.json', {
            'passed': len(passed),
            'warnings': len(warnings),
            'failed': len(blocking),
            'checks': [c.as_dict() for c in checks],
        })}
        if payload.get('tree_text'):
            artifacts['tree outline'] = context.write_text('bt_outline.txt',
                                                           payload['tree_text'])

        summary = f'{len(passed)}/{len(checks)} checks passed'
        if blocking:
            summary += f', {len(blocking)} failed'
        if warnings:
            summary += f', {len(warnings)} warning{"s" if len(warnings) > 1 else ""}'

        detail = {
            'checks run': len(checks),
            'passed': len(passed),
            'failed': len(blocking),
            'warnings': len(warnings),
        }
        if root is not None:
            kinds = [xml_tree.grammar().get(element.tag, ('unknown',))[0]
                     for element, _ in root.walk()]
            detail['nodes declared'] = len(kinds)
            detail['actions'] = kinds.count('action')
            detail['composites'] = kinds.count('composite')
            detail['decorators'] = kinds.count('decorator')
            detail['find and check nodes'] = kinds.count('find') + kinds.count('condition')
        if blocking:
            detail['first failure'] = f'{blocking[0].title}: {blocking[0].message}'

        self.log.info('%s', summary)
        return self.result(
            StageStatus.FAILED if blocking else StageStatus.PASSED,
            summary=summary, detail=detail, artifacts=artifacts, checks=checks,
            error=blocking[0].message if blocking else None)



def _is_decorator(node):
    import py_trees
    return isinstance(node, py_trees.decorators.Decorator)


def _as_text(root, depth=0):
    """A plain-text outline of the built tree, for the log and for bt_outline.txt."""
    marker = {'Sequence': '→', 'Selector': '?'}.get(type(root).__name__, '•')
    if marker == '•' and _is_decorator(root):
        marker = '◇'
    line = f'{"    " * depth}{marker} {root.name}'
    arguments = getattr(root, 'arguments', None)
    if arguments:
        line += '  (' + ', '.join(f'{k}={v!r}' for k, v in arguments.items()) + ')'
    lines = [line]
    for child in getattr(root, 'children', []):
        lines.append(_as_text(child, depth + 1))
    return '\n'.join(lines)
