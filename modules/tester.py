"""Stage 5 - the syntax tester.

This stage decides whether the generated ``create_behavior_tree()`` is well formed. It
is a *static* test: the code is parsed and inspected, never run against the simulator.
The only thing it executes is the construction of the tree itself, in a sandbox where
the four action nodes are harmless stand-ins, which is the only way to prove that the
function really does return a tree.

The checks are grouped, and each one reports on its own so a failure points at a line:

Syntax     - the code parses, and holds exactly one ``create_behavior_tree``.
Structure  - the mandated try/except, the ``Root`` sequence, ``memory=True``,
             unique node names and variables, no orphaned nodes.
Arguments  - each action gets exactly the arguments it takes, and ``times`` is an
             integer literal.
Scene      - every object id exists in the scene and is used in a role it can play.
Build      - the function constructs and returns a py_trees tree.

A check marked ``warning`` is reported but does not stop the run; only a failed
``error`` check does.
"""

import ast

from core.pipeline import Check, Stage, StageError, StageStatus

# The exact keyword arguments of each action node.
ACTION_SIGNATURES = {
    'Place': ('name', 'obj', 'location'),
    'Pour': ('name', 'source', 'target'),
    'Shake': ('name', 'obj', 'times'),
    'Close': ('name', 'obj', 'closing_obj'),
}

# The composites the prompt allows, and what they are called in the graph.
COMPOSITES = {
    'py_trees.composites.Sequence': 'sequence',
    'py_trees.composites.Selector': 'selector',
}

# Which action arguments must name a scene object, and the role that object must play.
OBJECT_ARGUMENTS = {
    ('Place', 'obj'): 'graspable',
    ('Place', 'location'): 'location',
    ('Pour', 'source'): 'graspable',
    ('Pour', 'target'): 'container',
    ('Shake', 'obj'): 'graspable',
    ('Close', 'obj'): 'graspable',
    ('Close', 'closing_obj'): 'cap',
}

FUNCTION_NAME = 'create_behavior_tree'
EXPECTED_LOG_LINE = 'logging.error(f"Error in create_behavior_tree: {e}")'

_UNKNOWN = object()  # an argument whose value is not a literal


# --- Small AST helpers -------------------------------------------------------

def _dotted(node):
    """Return 'py_trees.composites.Sequence' for an attribute chain, else None."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    return '.'.join(reversed(parts))


def _literal(node):
    """Return the literal value of a node, or _UNKNOWN when it is an expression."""
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError):
        return _UNKNOWN


class NodeCall:
    """One node constructed in the generated function."""

    def __init__(self, variable, constructor, kind, call):
        self.variable = variable
        self.constructor = constructor
        self.kind = kind                      # 'action', 'sequence' or 'selector'
        self.lineno = call.lineno
        self.positional = list(call.args)
        self.arguments = {kw.arg: kw.value for kw in call.keywords if kw.arg}
        self.values = {name: _literal(value) for name, value in self.arguments.items()}

    @property
    def node_name(self):
        value = self.values.get('name')
        return value if isinstance(value, str) else None

    @property
    def action(self):
        return self.constructor if self.kind == 'action' else None

    def __repr__(self):
        return f'<NodeCall {self.variable}={self.constructor} line {self.lineno}>'


class Analysis:
    """What the generated code says, collected once so the checks can read it."""

    def __init__(self, tree):
        self.module = tree
        self.function = None
        self.top_level_extras = []     # anything beside the function definition
        self.nodes = []                # NodeCall, in source order
        self.unknown_calls = []        # (dotted name, lineno) not allowed by the prompt
        self.add_children = []         # (target variable, [child variables], lineno)
        self.assignment_counts = {}    # variable -> how often it is assigned
        self.returned = None           # the variable the function returns
        self.try_node = None
        self.handlers = []

        self._collect_top_level()
        if self.function is not None:
            self._collect_body()

    # --- collection ------------------------------------------------------

    def _collect_top_level(self):
        for statement in self.module.body:
            if isinstance(statement, ast.FunctionDef) and statement.name == FUNCTION_NAME:
                if self.function is None:
                    self.function = statement
                else:
                    self.top_level_extras.append(statement)
            else:
                self.top_level_extras.append(statement)

    def _collect_body(self):
        body = self.function.body
        # The prompt requires the whole body to be one try/except.
        if len(body) == 1 and isinstance(body[0], ast.Try):
            self.try_node = body[0]
            self.handlers = self.try_node.handlers
            statements = self.try_node.body
        else:
            statements = body

        for statement in ast.walk(self.function):
            if isinstance(statement, ast.Return) and statement.value is not None:
                if isinstance(statement.value, ast.Name):
                    self.returned = statement.value.id

        for statement in statements:
            if isinstance(statement, ast.Assign) and len(statement.targets) == 1 \
                    and isinstance(statement.targets[0], ast.Name):
                variable = statement.targets[0].id
                self.assignment_counts[variable] = self.assignment_counts.get(variable, 0) + 1
                if isinstance(statement.value, ast.Call):
                    self._record_call(variable, statement.value)
            elif isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
                self._record_expression_call(statement.value)

    def _record_call(self, variable, call):
        name = call.func.id if isinstance(call.func, ast.Name) else _dotted(call.func)
        if name in ACTION_SIGNATURES:
            self.nodes.append(NodeCall(variable, name, 'action', call))
        elif name in COMPOSITES:
            self.nodes.append(NodeCall(variable, name, COMPOSITES[name], call))
        else:
            self.unknown_calls.append((name or ast.dump(call.func), call.lineno))

    def _record_expression_call(self, call):
        name = _dotted(call.func)
        if name and name.endswith('.add_children'):
            target = name[: -len('.add_children')]
            children = []
            if call.args and isinstance(call.args[0], (ast.List, ast.Tuple)):
                children = [c.id for c in call.args[0].elts if isinstance(c, ast.Name)]
            elif call.args:
                children = [c.id for c in call.args if isinstance(c, ast.Name)]
            self.add_children.append((target, children, call.lineno))
        elif name and name.endswith('.add_child'):
            target = name[: -len('.add_child')]
            children = [c.id for c in call.args if isinstance(c, ast.Name)]
            self.add_children.append((target, children, call.lineno))
        else:
            self.unknown_calls.append((name or 'call', call.lineno))

    # --- convenience -----------------------------------------------------

    def node(self, variable):
        for node in self.nodes:
            if node.variable == variable:
                return node
        return None

    @property
    def root(self):
        return self.node(self.returned) if self.returned else None

    @property
    def child_variables(self):
        used = []
        for _, children, _ in self.add_children:
            used.extend(children)
        return used


# --- The checks --------------------------------------------------------------

class SyntaxTestStage(Stage):
    """Check the generated function statically, then prove it builds a tree."""

    name = 'tester'
    title = 'Syntax check'
    description = 'Parse and check the generated function. Nothing is executed on the robot.'

    def execute(self, context, payload):
        code = payload.get('code')
        scene = payload.get('scene_object')
        if not code:
            raise StageError('There is no generated code to check.')

        checks = []

        # --- Syntax ------------------------------------------------------
        try:
            tree = ast.parse(code)
        except SyntaxError as error:
            checks.append(Check('syntax.parse', 'The code parses as Python', False,
                                f'{error.msg} (line {error.lineno}, column {error.offset})',
                                line=error.lineno, group='Syntax'))
            return self._report(context, payload, checks, built=None)

        checks.append(Check('syntax.parse', 'The code parses as Python', True,
                            'no syntax errors', group='Syntax'))

        analysis = Analysis(tree)
        checks.extend(self._check_syntax(analysis))
        if analysis.function is None:
            return self._report(context, payload, checks, built=None)

        checks.extend(self._check_structure(analysis))
        checks.extend(self._check_arguments(analysis))
        if scene is not None:
            checks.extend(self._check_scene(analysis, scene))

        # --- Build -------------------------------------------------------
        built, build_checks = self._check_build(code, analysis)
        checks.extend(build_checks)

        return self._report(context, payload, checks, built=built, analysis=analysis)

    # --- Syntax group ----------------------------------------------------

    def _check_syntax(self, analysis):
        checks = []
        checks.append(Check(
            'syntax.function', f'Defines {FUNCTION_NAME}()', analysis.function is not None,
            'found' if analysis.function is not None
            else f'no function named {FUNCTION_NAME} in the generated code',
            line=analysis.function.lineno if analysis.function else None, group='Syntax'))

        if analysis.function is not None:
            arguments = [a.arg for a in analysis.function.args.args]
            checks.append(Check(
                'syntax.signature', 'Takes no arguments', not arguments,
                'no parameters, as the prompt requires' if not arguments
                else f'unexpected parameters: {", ".join(arguments)}',
                line=analysis.function.lineno, severity='warning', group='Syntax'))

        extras = [type(node).__name__ for node in analysis.top_level_extras]
        checks.append(Check(
            'syntax.only_function', 'Nothing outside the function', not extras,
            'the code is only the function' if not extras
            else f'extra top-level code the prompt forbids: {", ".join(sorted(set(extras)))}',
            line=analysis.top_level_extras[0].lineno if extras else None,
            severity='warning', group='Syntax'))
        return checks

    # --- Structure group -------------------------------------------------

    def _check_structure(self, analysis):
        checks = []

        # The mandated try/except with the exact logging line.
        checks.append(Check(
            'structure.try', 'The body is one try/except block',
            analysis.try_node is not None,
            'present' if analysis.try_node is not None
            else 'the body is not wrapped in try/except',
            line=analysis.function.lineno, group='Structure'))

        if analysis.handlers:
            handler = analysis.handlers[0]
            catches = _dotted(handler.type) if handler.type is not None else None
            logged = ''
            if handler.body and isinstance(handler.body[0], ast.Expr):
                logged = ast.unparse(handler.body[0]).strip()
            correct = catches == 'Exception' and logged.replace("'", '"') == EXPECTED_LOG_LINE
            checks.append(Check(
                'structure.handler', 'The handler logs the mandated message', correct,
                'exactly as the prompt specifies' if correct
                else f'expected `{EXPECTED_LOG_LINE}`, found `{logged or "nothing"}`'
                     f'{"" if catches == "Exception" else f" and it catches {catches}"}',
                line=handler.lineno, group='Structure'))

        # The root: returned, a Sequence, named Root, with memory.
        root = analysis.root
        checks.append(Check(
            'structure.return', 'The function returns the root', root is not None,
            f'returns `{analysis.returned}`' if root is not None
            else f'returns `{analysis.returned or "nothing"}`, which is not a node '
                 f'created in this function',
            group='Structure'))

        if root is not None:
            checks.append(Check(
                'structure.root_type', 'The root is a Sequence named "Root"',
                root.kind == 'sequence' and root.node_name == 'Root',
                'correct' if root.kind == 'sequence' and root.node_name == 'Root'
                else f'the root is a {root.kind} named "{root.node_name}"',
                line=root.lineno, group='Structure'))

        # memory=True on every composite.
        bad_memory = [n for n in analysis.nodes
                      if n.kind in ('sequence', 'selector') and n.values.get('memory') is not True]
        checks.append(Check(
            'structure.memory', 'Every Sequence and Selector has memory=True',
            not bad_memory,
            f'all {sum(1 for n in analysis.nodes if n.kind != "action")} composites set it'
            if not bad_memory
            else 'missing on: ' + ', '.join(f'{n.variable} (line {n.lineno})' for n in bad_memory),
            line=bad_memory[0].lineno if bad_memory else None, group='Structure'))

        # Only the allowed constructors.
        checks.append(Check(
            'structure.allowed_nodes', 'Only the four actions and py_trees composites',
            not analysis.unknown_calls,
            f'{len(analysis.nodes)} nodes, all allowed' if not analysis.unknown_calls
            else 'not allowed: ' + ', '.join(f'{name} (line {line})'
                                             for name, line in analysis.unknown_calls),
            line=analysis.unknown_calls[0][1] if analysis.unknown_calls else None,
            group='Structure'))

        # Unique node names, and PascalCase.
        names = [n.node_name for n in analysis.nodes if n.node_name]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        checks.append(Check(
            'structure.unique_names', 'Every node name is unique', not duplicates,
            f'{len(names)} distinct names' if not duplicates
            else 'used more than once: ' + ', '.join(duplicates), group='Structure'))

        not_pascal = [n for n in analysis.nodes
                      if n.node_name and not n.node_name[:1].isupper()]
        checks.append(Check(
            'structure.name_style', 'Node names are PascalCase', not not_pascal,
            'all names start with a capital' if not not_pascal
            else 'not PascalCase: ' + ', '.join(f'"{n.node_name}"' for n in not_pascal),
            severity='warning', group='Structure'))

        # Unique variables.
        reassigned = sorted(v for v, count in analysis.assignment_counts.items() if count > 1)
        checks.append(Check(
            'structure.unique_variables', 'Every node variable is assigned once',
            not reassigned,
            f'{len(analysis.assignment_counts)} variables' if not reassigned
            else 'assigned more than once: ' + ', '.join(reassigned), group='Structure'))

        # No orphans: every node but the root is a child of exactly one composite.
        used = analysis.child_variables
        orphans = [n.variable for n in analysis.nodes
                   if n.variable != analysis.returned and n.variable not in used]
        twice = sorted({v for v in used if used.count(v) > 1})
        checks.append(Check(
            'structure.reachable', 'Every node is attached to the tree', not orphans,
            'no orphaned nodes' if not orphans
            else 'created but never added as a child: ' + ', '.join(orphans),
            group='Structure'))
        checks.append(Check(
            'structure.single_parent', 'No node is added twice', not twice,
            'each node has one parent' if not twice
            else 'added under more than one parent: ' + ', '.join(twice), group='Structure'))

        # Unknown children: a variable added as a child that was never created.
        known = {n.variable for n in analysis.nodes}
        ghosts = sorted({v for v in used if v not in known})
        checks.append(Check(
            'structure.known_children', 'Every child was created above', not ghosts,
            'all children exist' if not ghosts
            else 'added as a child but never created: ' + ', '.join(ghosts), group='Structure'))

        root_additions = [line for target, _, line in analysis.add_children
                          if target == analysis.returned]
        checks.append(Check(
            'structure.one_root_call', 'The root children are added in one call',
            len(root_additions) <= 1,
            'one add_children call on the root' if len(root_additions) <= 1
            else f'{len(root_additions)} calls, on lines '
                 f'{", ".join(str(line) for line in root_additions)}',
            severity='warning', group='Structure'))
        return checks

    # --- Arguments group -------------------------------------------------

    def _check_arguments(self, analysis):
        checks = []
        problems = []
        for node in analysis.nodes:
            if node.kind != 'action':
                continue
            expected = set(ACTION_SIGNATURES[node.constructor])
            given = set(node.arguments)
            missing = expected - given
            unexpected = given - expected
            if node.positional:
                problems.append(f'{node.constructor} on line {node.lineno} passes '
                                f'{len(node.positional)} positional argument(s); the prompt '
                                f'uses keywords only')
            if missing:
                problems.append(f'{node.constructor} on line {node.lineno} is missing '
                                f'{", ".join(sorted(missing))}')
            if unexpected:
                problems.append(f'{node.constructor} on line {node.lineno} does not take '
                                f'{", ".join(sorted(unexpected))}')

        checks.append(Check(
            'arguments.signatures', 'Every action gets exactly its own arguments',
            not problems,
            f'{sum(1 for n in analysis.nodes if n.kind == "action")} action nodes are correct'
            if not problems else '; '.join(problems), group='Arguments'))

        # Shake(times=...) must be an integer literal.
        bad_times = []
        for node in analysis.nodes:
            if node.constructor != 'Shake':
                continue
            value = node.values.get('times', _UNKNOWN)
            if not isinstance(value, int) or isinstance(value, bool):
                shown = 'missing' if 'times' not in node.arguments else (
                    ast.unparse(node.arguments['times']))
                bad_times.append(f'line {node.lineno}: times={shown}')
        checks.append(Check(
            'arguments.times', 'Shake gets an integer number of times', not bad_times,
            'all Shake counts are integer literals' if not bad_times
            else '; '.join(bad_times), group='Arguments'))

        # Every node must have a name.
        unnamed = [n for n in analysis.nodes if not n.node_name]
        checks.append(Check(
            'arguments.names', 'Every node has a literal name', not unnamed,
            'all nodes are named' if not unnamed
            else 'no literal name on: ' + ', '.join(
                f'{n.variable} (line {n.lineno})' for n in unnamed), group='Arguments'))
        return checks

    # --- Scene group -----------------------------------------------------

    def _check_scene(self, analysis, scene):
        """Check every object id against the scene the model was shown."""
        checks = []
        unknown, wrong_role = [], []

        for node in analysis.nodes:
            if node.kind != 'action':
                continue
            for argument, required in (
                    (a, r) for (action, a), r in OBJECT_ARGUMENTS.items()
                    if action == node.constructor):
                value = node.values.get(argument, _UNKNOWN)
                if not isinstance(value, str):
                    continue  # a missing or non-literal id is already reported above
                obj = scene.by_id(value)
                if obj is None:
                    unknown.append(f'line {node.lineno}: "{value}" is not in the scene')
                    continue
                if required == 'location' and not obj.is_location:
                    wrong_role.append(f'line {node.lineno}: "{value}" is {obj.role}, not a '
                                      f'valid location')
                elif required == 'graspable' and obj.is_location:
                    wrong_role.append(f'line {node.lineno}: "{value}" is a valid location '
                                      f'and cannot be grasped')
                elif required == 'container' and not obj.is_container:
                    wrong_role.append(f'line {node.lineno}: nothing can be poured into '
                                      f'"{value}" ({obj.name})')
                elif required == 'cap' and not obj.is_cap:
                    wrong_role.append(f'line {node.lineno}: "{value}" ({obj.name}) is not a '
                                      f'cap or lid')

        checks.append(Check(
            'scene.ids', 'Every object id exists in the scene', not unknown,
            f'all ids match scene {scene.number}' if not unknown else '; '.join(unknown),
            group='Scene'))
        checks.append(Check(
            'scene.roles', 'Every object is used in a role it can play', not wrong_role,
            'graspable objects are grasped, locations are used as locations'
            if not wrong_role else '; '.join(wrong_role), group='Scene'))

        # The prompt's spill rule: shaking a container that holds liquid needs a Close
        # on that same object first. Reported as a warning - it is the prompt's own
        # physical rule rather than a syntax error.
        order = [n for n in analysis.nodes if n.kind == 'action']
        unclosed = []
        for index, node in enumerate(order):
            if node.constructor != 'Shake':
                continue
            target = node.values.get('obj')
            obj = scene.by_id(target) if isinstance(target, str) else None
            if obj is None or not obj.holds_liquid:
                continue
            closed_before = any(
                earlier.constructor == 'Close' and earlier.values.get('obj') == target
                for earlier in order[:index])
            if not closed_before:
                unclosed.append(f'line {node.lineno}: "{target}" holds liquid and is shaken '
                                f'without being closed first')
        checks.append(Check(
            'scene.spill', 'A container holding liquid is closed before it is shaken',
            not unclosed,
            'no open container is shaken' if not unclosed else '; '.join(unclosed),
            severity='warning', group='Scene'))
        return checks

    # --- Build group -----------------------------------------------------

    def _check_build(self, code, analysis):
        """Construct the tree in a sandbox and confirm it is a real py_trees tree."""
        try:
            import py_trees
        except ImportError as error:
            return None, [Check('build.py_trees', 'py_trees is installed', False,
                                f'{error} — install it with: pip install py_trees',
                                group='Build')]

        namespace = _sandbox(py_trees)
        checks = []
        try:
            exec(compile(code, '<generated>', 'exec'), namespace)  # noqa: S102
        except Exception as error:  # noqa: BLE001
            return None, [Check('build.exec', 'The function definition loads', False,
                                f'{type(error).__name__}: {error}', group='Build')]

        function = namespace.get(FUNCTION_NAME)
        if not callable(function):
            return None, [Check('build.exec', 'The function definition loads', False,
                                f'{FUNCTION_NAME} is not callable after loading',
                                group='Build')]

        try:
            root = function()
        except Exception as error:  # noqa: BLE001
            return None, [Check('build.call', f'{FUNCTION_NAME}() constructs a tree', False,
                                f'{type(error).__name__}: {error}', group='Build')]

        if root is None:
            # The try/except swallowed the real error. Run the body again without it so
            # the message says what actually went wrong.
            hidden = _error_behind_try(code, py_trees)
            return None, [Check(
                'build.call', f'{FUNCTION_NAME}() constructs a tree', False,
                f'it returned None — the try/except hid the error: {hidden}'
                if hidden else 'it returned None instead of the root node',
                group='Build')]

        checks.append(Check('build.call', f'{FUNCTION_NAME}() constructs a tree', True,
                            f'returned {type(root).__name__}(name="{root.name}")',
                            group='Build'))

        is_tree = isinstance(root, py_trees.behaviour.Behaviour)
        checks.append(Check(
            'build.type', 'The returned object is a py_trees node', is_tree,
            f'{type(root).__name__}' if is_tree
            else f'got {type(root).__name__}, which is not a py_trees Behaviour',
            group='Build'))

        if is_tree:
            built_nodes = sum(1 for _ in root.iterate())
            declared = len(analysis.nodes)
            checks.append(Check(
                'build.node_count', 'Every declared node is in the built tree',
                built_nodes == declared,
                f'{built_nodes} nodes' if built_nodes == declared
                else f'{declared} nodes were declared but the built tree has {built_nodes}',
                group='Build'))

        return (root if is_tree else None), checks

    # --- Reporting -------------------------------------------------------

    def _report(self, context, payload, checks, built, analysis=None):
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
        if analysis is not None:
            detail['nodes declared'] = len(analysis.nodes)
            detail['actions'] = sum(1 for n in analysis.nodes if n.kind == 'action')
            detail['composites'] = sum(1 for n in analysis.nodes if n.kind != 'action')
        if blocking:
            detail['first failure'] = f'{blocking[0].title}: {blocking[0].message}'

        self.log.info('%s', summary)
        return self.result(
            StageStatus.FAILED if blocking else StageStatus.PASSED,
            summary=summary, detail=detail, artifacts=artifacts, checks=checks,
            error=blocking[0].message if blocking else None)


# --- The sandbox -------------------------------------------------------------

def _sandbox(py_trees):
    """A namespace where the four actions are stand-ins that build but never act.

    The composites are the real py_trees ones, so the result is a real py_trees tree
    that can be rendered and later ticked - only the leaves are inert.
    """
    import logging as logging_module

    class StubAction(py_trees.behaviour.Behaviour):
        """A leaf that records the arguments it was given and always succeeds."""

        action = 'Action'

        def __init__(self, name='', **arguments):
            super().__init__(name=name)
            self.arguments = arguments

        def update(self):
            return py_trees.common.Status.SUCCESS

    actions = {}
    for action in ACTION_SIGNATURES:
        actions[action] = type(action, (StubAction,), {'action': action})

    return {'py_trees': py_trees, 'logging': logging_module, '__builtins__': __builtins__,
            **actions}


def _error_behind_try(code, py_trees):
    """Re-run the function body without its try/except, to surface the hidden error."""
    try:
        tree = ast.parse(code)
        function = next(node for node in tree.body
                        if isinstance(node, ast.FunctionDef) and node.name == FUNCTION_NAME)
        if len(function.body) != 1 or not isinstance(function.body[0], ast.Try):
            return None
        function.body = function.body[0].body
        ast.fix_missing_locations(tree)
        namespace = _sandbox(py_trees)
        exec(compile(tree, '<generated-no-try>', 'exec'), namespace)  # noqa: S102
        namespace[FUNCTION_NAME]()
    except Exception as error:  # noqa: BLE001 - this is exactly what we want to read
        return f'{type(error).__name__}: {error}'
    return None


def _as_text(root, depth=0):
    """A plain-text outline of the built tree, for the log and for bt_outline.txt."""
    marker = {'Sequence': '→', 'Selector': '?'}.get(type(root).__name__, '•')
    line = f'{"    " * depth}{marker} {root.name}'
    arguments = getattr(root, 'arguments', None)
    if arguments:
        line += '  (' + ', '.join(f'{k}={v!r}' for k, v in arguments.items()) + ')'
    lines = [line]
    for child in getattr(root, 'children', []):
        lines.append(_as_text(child, depth + 1))
    return '\n'.join(lines)
