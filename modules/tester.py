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
Arguments  - each node gets exactly the arguments it takes, and counts such as
             ``times`` are integer literals.
Scene      - every object id exists in the scene and is used in a role it can play.
Build      - the function constructs and returns a py_trees tree.

A check marked ``warning`` is reported but does not stop the run; only a failed
``error`` check does.
"""

import ast

import config
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


def _signatures(module, table):
    """``{'py_trees.<module>.<Name>': (required, optional)}`` for a table of nodes."""
    return {f'py_trees.{module}.{name}': arguments for name, arguments in table.items()}


_CHILD_ONLY = (('name', 'child'), ())

# The decorators the prompt allows (py_trees.decorators): required and optional keywords.
DECORATOR_SIGNATURES = _signatures('decorators', {
    'Retry': (('name', 'child', 'num_failures'), ()),
    'Repeat': (('name', 'child', 'num_success'), ()),
    'Timeout': (('name', 'child'), ('duration',)),
    'Inverter': _CHILD_ONLY,
    'FailureIsSuccess': _CHILD_ONLY,
    'FailureIsRunning': _CHILD_ONLY,
    'SuccessIsFailure': _CHILD_ONLY,
    'SuccessIsRunning': _CHILD_ONLY,
    'RunningIsFailure': _CHILD_ONLY,
    'RunningIsSuccess': _CHILD_ONLY,
    'OneShot': (('name', 'child', 'policy'), ()),
    'Condition': (('name', 'child', 'status'), ()),
    'EternalGuard': (('name', 'child', 'condition'), ('blackboard_keys',)),
    'StatusToBlackboard': (('name', 'child', 'variable_name'), ()),
    'Count': _CHILD_ONLY,
    'PassThrough': _CHILD_ONLY,
    'ForEach': (('name', 'child', 'source_key', 'target_key'), ()),
})

# The condition and blackboard behaviours the prompt allows (py_trees.behaviours).
BEHAVIOUR_SIGNATURES = _signatures('behaviours', {
    'SetBlackboardVariable': (('name', 'variable_name', 'variable_value', 'overwrite'), ()),
    'UnsetBlackboardVariable': (('name', 'key'), ()),
    'CheckBlackboardVariableExists': (('name', 'variable_name'), ()),
    'CheckBlackboardVariableValue': (('name', 'check'), ()),
    'CheckBlackboardVariableValues': (('name', 'checks', 'operator'), ('namespace',)),
    'CompareBlackboardVariables': (('name', 'var1_key', 'var2_key', 'operator'), ()),
    'WaitForBlackboardVariable': (('name', 'variable_name'), ()),
    'WaitForBlackboardVariableValue': (('name', 'check'), ()),
    'BlackboardToStatus': (('name', 'variable_name'), ()),
    'Success': (('name',), ()),
    'Failure': (('name',), ()),
    'Running': (('name',), ()),
})

# Objects the prompt builds a check from. They are not tree nodes.
HELPER_SIGNATURES = {
    'py_trees.common.ComparisonExpression': (('variable', 'value', 'operator'), ()),
}

def allowed_nodes():
    """The decorators, behaviours and helpers the prompt allows: ``config.GRAMMAR_*``.

    Read on every call, so a change in the config takes effect without a restart. A node
    that py_trees has but the prompt does not name is reported as not allowed.
    """
    def pick(table, names):
        return {name: signature for name, signature in table.items()
                if name.rsplit('.', 1)[-1] in names}

    return (pick(DECORATOR_SIGNATURES, config.GRAMMAR_DECORATORS),
            pick(BEHAVIOUR_SIGNATURES, config.GRAMMAR_BEHAVIOURS),
            pick(HELPER_SIGNATURES, config.GRAMMAR_HELPERS))


# Arguments that must be integer literals, by node: "do it n times" with a string "3"
# would build, then fail when the tree runs.
COUNT_ARGUMENTS = {
    'Shake': 'times',
    'py_trees.decorators.Retry': 'num_failures',
    'py_trees.decorators.Repeat': 'num_success',
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
        # 'action', 'sequence', 'selector', 'decorator' or 'behaviour'
        self.kind = kind
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

    @property
    def short_name(self):
        """``Retry`` for ``py_trees.decorators.Retry``."""
        return self.constructor.rsplit('.', 1)[-1]

    @property
    def signature(self):
        """``(required, optional)`` keywords of this node, from the tables above."""
        if self.kind == 'action':
            return ACTION_SIGNATURES[self.constructor], ()
        if self.kind == 'decorator':
            return DECORATOR_SIGNATURES[self.constructor]
        if self.kind == 'behaviour':
            return BEHAVIOUR_SIGNATURES[self.constructor]
        return (), ()

    def __repr__(self):
        return f'<NodeCall {self.variable}={self.constructor} line {self.lineno}>'


class Analysis:
    """What the generated code says, collected once so the checks can read it."""

    def __init__(self, tree):
        self.module = tree
        self.allowed = allowed_nodes()  # (decorators, behaviours, helpers) of the grammar
        self.function = None
        self.top_level_extras = []     # anything beside the function definition
        self.nodes = []                # NodeCall, in source order
        self.helpers = []              # NodeCall for objects that are not nodes
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
        elif name in DECORATOR_SIGNATURES:
            node = NodeCall(variable, name, 'decorator', call)
            self.nodes.append(node)
            # A decorator's child is attached by the constructor, not by add_children.
            child = node.arguments.get('child')
            if isinstance(child, ast.Name):
                self.add_children.append((variable, [child.id], call.lineno))
            self._refuse_unless_allowed(name, self.allowed[0], call)
        elif name in BEHAVIOUR_SIGNATURES:
            self.nodes.append(NodeCall(variable, name, 'behaviour', call))
            self._refuse_unless_allowed(name, self.allowed[1], call)
        elif name in HELPER_SIGNATURES:
            self.helpers.append(NodeCall(variable, name, 'helper', call))
            self._refuse_unless_allowed(name, self.allowed[2], call)
        else:
            self.unknown_calls.append((name or ast.dump(call.func), call.lineno))

    def _refuse_unless_allowed(self, name, allowed, call):
        """A node py_trees has but the prompt does not name is still recorded, so the
        other checks stay consistent, and reported once as not allowed."""
        if name not in allowed:
            self.unknown_calls.append((name, call.lineno))

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

    def check(self, code, scene=None):
        """Run every check against one piece of generated code.

        Returns ``(checks, built_tree_or_None, analysis_or_None)``. This is what the
        generation loop calls for each attempt; :meth:`execute` wraps it so the stage
        still works on its own.
        """
        checks = []

        # --- Syntax ------------------------------------------------------
        try:
            tree = ast.parse(code)
        except SyntaxError as error:
            checks.append(Check('syntax.parse', 'The code parses as Python', False,
                                f'{error.msg} (line {error.lineno}, column {error.offset})',
                                line=error.lineno, group='Syntax'))
            return checks, None, None

        checks.append(Check('syntax.parse', 'The code parses as Python', True,
                            'no syntax errors', group='Syntax'))

        analysis = Analysis(tree)
        checks.extend(self._check_syntax(analysis))
        if analysis.function is None:
            return checks, None, analysis

        checks.extend(self._check_structure(analysis))
        checks.extend(self._check_arguments(analysis))
        if scene is not None:
            checks.extend(self._check_scene(analysis, scene))

        # --- Build -------------------------------------------------------
        built, build_checks = self._check_build(code, analysis)
        checks.extend(build_checks)

        return checks, built, analysis

    @staticmethod
    def passed(checks):
        """True when no blocking check failed. Warnings never stop a run."""
        return not any(check.blocking for check in checks)

    def execute(self, context, payload):
        code = payload.get('code')
        scene = payload.get('scene_object')
        if not code:
            raise StageError('There is no generated code to check.')

        checks, built, analysis = self.check(code, scene)
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
                # A different message in the except block is cosmetic: the code still
                # runs, so it must not cost a repair round.
                line=handler.lineno, severity='warning', group='Structure'))

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
            f'all {sum(1 for n in analysis.nodes if n.kind in ("sequence", "selector"))} '
            f'composites set it'
            if not bad_memory
            else 'missing on: ' + ', '.join(f'{n.variable} (line {n.lineno})' for n in bad_memory),
            line=bad_memory[0].lineno if bad_memory else None, group='Structure'))

        # Only the allowed constructors.
        checks.append(Check(
            'structure.allowed_nodes', 'Only the nodes the prompt allows',
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
        with_arguments = [n for n in (*analysis.nodes, *analysis.helpers)
                          if n.kind in ('action', 'decorator', 'behaviour', 'helper')]
        for node in with_arguments:
            required, optional = (HELPER_SIGNATURES[node.constructor] if node.kind == 'helper'
                                  else node.signature)
            given = set(node.arguments)
            missing = set(required) - given
            unexpected = given - set(required) - set(optional)
            label = node.constructor if node.kind in ('action', 'helper') else node.short_name
            if node.positional:
                problems.append(f'{label} on line {node.lineno} passes '
                                f'{len(node.positional)} positional argument(s); the prompt '
                                f'uses keywords only')
            if missing:
                problems.append(f'{label} on line {node.lineno} is missing '
                                f'{", ".join(sorted(missing))}')
            if unexpected:
                problems.append(f'{label} on line {node.lineno} does not take '
                                f'{", ".join(sorted(unexpected))}')

        checks.append(Check(
            'arguments.signatures', 'Every node gets exactly its own arguments',
            not problems,
            f'{len(with_arguments)} nodes and checks are correct'
            if not problems else '; '.join(problems), group='Arguments'))

        # Counts such as Shake(times=...) must be integer literals.
        bad_counts = []
        for node in analysis.nodes:
            argument = COUNT_ARGUMENTS.get(node.constructor)
            if argument is None:
                continue
            value = node.values.get(argument, _UNKNOWN)
            if not isinstance(value, int) or isinstance(value, bool):
                shown = 'missing' if argument not in node.arguments else (
                    ast.unparse(node.arguments[argument]))
                bad_counts.append(f'line {node.lineno}: {argument}={shown}')
        checks.append(Check(
            'arguments.counts', 'Counts are integers', not bad_counts,
            'all counts are integer literals' if not bad_counts
            else '; '.join(bad_counts), group='Arguments'))

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

        namespace = _sandbox(py_trees, code)
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
            detail['composites'] = sum(1 for n in analysis.nodes
                                       if n.kind in ('sequence', 'selector'))
            detail['decorators'] = sum(1 for n in analysis.nodes if n.kind == 'decorator')
            detail['behaviours'] = sum(1 for n in analysis.nodes if n.kind == 'behaviour')
        if blocking:
            detail['first failure'] = f'{blocking[0].title}: {blocking[0].message}'

        self.log.info('%s', summary)
        return self.result(
            StageStatus.FAILED if blocking else StageStatus.PASSED,
            summary=summary, detail=detail, artifacts=artifacts, checks=checks,
            error=blocking[0].message if blocking else None)


# --- Automatic labels (analysis only) -----------------------------------------

def spill_label(analysis, scene):
    """Whether the tree shakes an open container that holds liquid.

    This was once a check here. It is a physical rule, so judging it is now the
    semantic judge's job - but it is cheap and exact, so it is still computed and
    written to ``analysis_labels.json`` as an automatic label for evaluating the judge
    later. It is never shown to the generator or to the judge, and it never changes a
    status.
    """
    if analysis is None or scene is None:
        return None

    order = [node for node in analysis.nodes if node.kind == 'action']
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

    return {'shakes_open_container': bool(unclosed), 'details': unclosed}


# --- The sandbox -------------------------------------------------------------

def _sandbox(py_trees, source=''):
    """A namespace where the four actions are stand-ins that build but never act.

    The composites, decorators and behaviours are the real py_trees ones, so the result
    is a real py_trees tree that can be rendered and later ticked - only the action
    leaves are inert. Decorators and behaviours also remember the arguments they were
    built with, so the tree can be described afterwards as the actions already are.
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

    return {'py_trees': _RecordingPyTrees(py_trees, _LambdaSources(source)),
            'logging': logging_module, '__builtins__': __builtins__, **actions}


class _LambdaSources:
    """Finds the source text of a lambda that the generated code passed as an argument."""

    def __init__(self, source):
        self.by_line = {}
        try:
            for node in ast.walk(ast.parse(source)):
                if isinstance(node, ast.Lambda):
                    self.by_line.setdefault(node.lineno, []).append(node)
        except SyntaxError:
            pass

    def of(self, function):
        code = function.__code__
        candidates = self.by_line.get(code.co_firstlineno, [])
        names = list(code.co_varnames[:code.co_argcount])
        for node in candidates:
            if [a.arg for a in node.args.args] == names:
                return ast.unparse(node)
        return 'lambda'


def _describe(value, lambdas):
    """An argument as plain data that can be shown and saved."""
    import enum

    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple, set)):
        return [_describe(item, lambdas) for item in value]
    if isinstance(value, enum.Enum):
        return f'{type(value).__name__}.{value.name}'
    if hasattr(value, 'variable') and hasattr(value, 'operator'):   # ComparisonExpression
        compared = value.value_generator() if hasattr(value, 'value_generator') else None
        return (f'ComparisonExpression(variable={value.variable!r}, value={compared!r}, '
                f'operator={_describe(value.operator, lambdas)})')
    if callable(value) and getattr(value, '__name__', '') == '<lambda>':
        return lambdas.of(value)
    if callable(value):
        return getattr(value, '__name__', repr(value))
    return repr(value)


class _RecordingModule:
    """A py_trees module whose behaviours remember the keyword arguments they got."""

    def __init__(self, module, lambdas):
        self._module, self._lambdas, self._classes = module, lambdas, {}

    def __getattr__(self, name):
        attribute = getattr(self._module, name)
        import py_trees
        if not (isinstance(attribute, type)
                and issubclass(attribute, py_trees.behaviour.Behaviour)):
            return attribute
        if name not in self._classes:
            lambdas = self._lambdas

            def __init__(self, *args, **kwargs):
                attribute.__init__(self, *args, **kwargs)
                self.arguments = {}
                for key, value in kwargs.items():
                    if key in ('name', 'child'):
                        continue
                    try:
                        self.arguments[key] = _describe(value, lambdas)
                    except Exception:  # noqa: BLE001 - describing must never stop the build
                        self.arguments[key] = repr(value)

            self._classes[name] = type(name, (attribute,), {
                '__init__': __init__, '__module__': attribute.__module__,
                '__doc__': attribute.__doc__})
        return self._classes[name]


class _RecordingPyTrees:
    """``py_trees`` as the generated code sees it: the real module, with recording
    decorators and behaviours."""

    def __init__(self, py_trees, lambdas):
        self._py_trees = py_trees
        self.decorators = _RecordingModule(py_trees.decorators, lambdas)
        self.behaviours = _RecordingModule(py_trees.behaviours, lambdas)

    def __getattr__(self, name):
        return getattr(self._py_trees, name)


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
        namespace = _sandbox(py_trees, code)
        exec(compile(tree, '<generated-no-try>', 'exec'), namespace)  # noqa: S102
        namespace[FUNCTION_NAME]()
    except Exception as error:  # noqa: BLE001 - this is exactly what we want to read
        return f'{type(error).__name__}: {error}'
    return None


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
