"""Reading, checking and building a behavior tree that the generator wrote as XML.

Goes to ``modules/xml_tree.py``. ``modules/tester.py`` calls :func:`check_xml` instead of
its Python checks; the loop calls :func:`extract_xml` instead of ``extract_code``.

The tree is the BehaviorTree.CPP XML format that py_trees 2.6 reads
(``py_trees.parsers.behaviour_tree_xml``)::

    <root main_tree_to_execute="MainTree">
      <BehaviorTree ID="MainTree">
        <Sequence name="Root" memory="true">
          <FindOne name="FindRack" key="rack" type="box"/>
          ...
        </Sequence>
      </BehaviorTree>
    </root>

Two spellings matter. A key that a node stores or loops over is a plain name
(``key="rack"``, ``source_key="tubes"``, ``target_key="tube"``, and the list a HasCount
counts). An object a node acts on is that key in curly braces (``obj="{rack}"``), which
the parser wires to the blackboard entry ``/rack``. This is the generic prompt's old
``@rack``, in the notation py_trees itself uses.

The py_trees parser accepts more than the prompt allows - any py_trees decorator, a
missing required port, a key nothing stores, ``times="two"`` - and its errors carry no
line numbers. So the document is first read with its line numbers and checked here,
group by group as before (Syntax, Structure, Arguments, Objects); only a tree that
passes those is handed to the parser (Build). A tree is never executed here.
"""

import re
import tempfile
import xml.parsers.expat
from dataclasses import dataclass, field
from pathlib import Path

import config
from core.pipeline import Check

MAIN_TREE_ID = 'MainTree'

# --- Getting the XML out of the reply ------------------------------------------

_XML_BLOCK = re.compile(r'```xml[ \t]*\n?(.*?)```', re.DOTALL | re.IGNORECASE)
_ANY_BLOCK = re.compile(r'```[a-zA-Z]*[ \t]*\n?(.*?)```', re.DOTALL)


def extract_xml(answer):
    """Return the XML document in the reply, or None when the reply holds no tree.

    Takes the ```xml block; failing that, any fenced block holding a <root> element; and
    failing that, a bare <root> ... </root> in the text, for a model that forgets the
    fence. None is what the loop treats as "no tree in the reply".
    """
    match = _XML_BLOCK.search(answer)
    if match:
        return match.group(1).strip()
    for block in _ANY_BLOCK.findall(answer):
        if '<root' in block:
            return block.strip()
    start, end = answer.find('<root'), answer.rfind('</root>')
    if start != -1 and end > start:
        return answer[start:end + len('</root>')].strip()
    return None


# --- Reading the document with its line numbers ----------------------------------

@dataclass
class Element:
    """One XML element, with the line it starts on. ElementTree keeps no line numbers."""

    tag: str
    attrib: dict
    line: int
    children: list = field(default_factory=list)

    @property
    def name(self):
        return self.attrib.get('name', '')

    def walk(self, parent=None):
        """``(element, parent)`` for this element and everything under it, in tree order."""
        yield self, parent
        for child in self.children:
            yield from child.walk(self)


class XMLReadError(ValueError):
    def __init__(self, message, line, column):
        super().__init__(message)
        self.message, self.line, self.column = message, line, column


def read_xml(text):
    """Return ``(document element, stray text)``; raise XMLReadError if it is not XML.

    Stray text is ``[(line, text)]`` for text written between tags, which the parser
    ignores. Comments are ignored, as the parser ignores them.
    """
    parser = xml.parsers.expat.ParserCreate()
    stack, top, stray = [], [], []

    def start(tag, attributes):
        element = Element(tag, dict(attributes), parser.CurrentLineNumber)
        (stack[-1].children if stack else top).append(element)
        stack.append(element)

    def end(_tag):
        stack.pop()

    def characters(data):
        if data.strip():
            stray.append((parser.CurrentLineNumber, data.strip()))

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = characters
    try:
        parser.Parse(text, True)
    except xml.parsers.expat.ExpatError as error:
        raise XMLReadError(xml.parsers.expat.ErrorString(error.code),
                           error.lineno, error.offset + 1) from error
    return top[0], stray


# --- The grammar -----------------------------------------------------------------

# What an attribute holds.
OBJECT = 'object'        # {key}: one object a find node or a ForEach stored
STORE = 'store'          # plain key a find node stores under
TARGET = 'target'        # plain key a ForEach stores each item under
LIST = 'list'            # plain key of a list a FindAll stored
POSITIVE = 'positive'    # whole number of 1 or more
COUNT = 'count'          # whole number of 0 or more
SECONDS = 'seconds'      # number above 0
POSITION = 'position'
COMPARISON = 'comparison'
PROPERTY = 'property'    # a perception property used to describe an object
PROPERTY_NAME = 'property_name'
PROPERTY_VALUE = 'property_value'
MEMORY = 'memory'


def perception_properties():
    """The property names a find node may describe an object with: ``config.PERCEPTION_*``."""
    return ('type', *config.PERCEPTION_COLOR_PROPERTIES, *config.PERCEPTION_BOOLEAN_PROPERTIES)


def _find(counted):
    return ({'key': STORE},
            {'position': POSITION, counted: POSITIVE,
             **{prop: PROPERTY for prop in perception_properties()}})


# tag: (kind, required attributes, optional attributes). Every node also takes name.
LEAVES = {
    'Place': ('action', {'obj': OBJECT, 'location': OBJECT}, {}),
    'Pour': ('action', {'source': OBJECT, 'target': OBJECT}, {}),
    'Shake': ('action', {'obj': OBJECT, 'times': POSITIVE}, {}),
    'Close': ('action', {'obj': OBJECT, 'closing_obj': OBJECT}, {}),
    'FindOne': ('find', *_find('nth')),
    'FindAll': ('find', *_find('limit')),
    'HasProperty': ('condition', {'obj': OBJECT, 'property': PROPERTY_NAME,
                                  'value': PROPERTY_VALUE}, {}),
    'HasCount': ('condition', {'key': LIST, 'count': COUNT}, {'comparison': COMPARISON}),
}
COMPOSITES = {
    'Sequence': ('composite', {}, {'memory': MEMORY}),
    'Selector': ('composite', {}, {'memory': MEMORY}),
}
# Every decorator the checks know. Only those in config.GRAMMAR_DECORATORS are allowed.
DECORATORS = {
    'ForEach': ('decorator', {'source_key': LIST, 'target_key': TARGET}, {}),
    'Inverter': ('decorator', {}, {}),
    'Retry': ('decorator', {'num_failures': POSITIVE}, {}),
    'Repeat': ('decorator', {'num_success': POSITIVE}, {}),
    'Timeout': ('decorator', {}, {'duration': SECONDS}),
    'FailureIsSuccess': ('decorator', {}, {}),
}
CONDITIONS = ('HasProperty', 'HasCount')

# Tags py_trees or BehaviorTree.CPP know, with what to tell the generator instead.
NOT_IN_GRAMMAR = {
    'Fallback': 'write Selector',
    'Parallel': 'the prompt has no Parallel',
    'SubTree': 'write the nodes out instead of a SubTree',
    'SubTreePlus': 'write the nodes out instead of a SubTree',
    'Include': 'the whole tree belongs in one document',
    'Import': 'the whole tree belongs in one document',
}

_PLAIN_KEY = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
_REFERENCE = re.compile(r'^\{([A-Za-z_][A-Za-z0-9_]*)\}$')
_NAME = re.compile(r'^[A-Za-z][A-Za-z0-9_]*$')


def grammar():
    """``{tag: (kind, required, optional)}`` for every tag the prompt allows right now."""
    allowed = {tag: entry for tag, entry in DECORATORS.items()
               if tag in config.GRAMMAR_DECORATORS}
    return {**LEAVES, **COMPOSITES, **allowed}


def _integer(value):
    return int(value) if re.fullmatch(r'\d+', value or '') else None


def _boolean(value):
    lowered = (value or '').lower()
    return {'true': True, 'false': False}.get(lowered)


def typed(kind, value, prop=None):
    """An attribute's value as the node receives it, for the graph and the judge outline."""
    if kind in (POSITIVE, COUNT):
        number = _integer(value)
        return value if number is None else number
    if kind == SECONDS:
        try:
            return float(value) if '.' in value else int(value)
        except ValueError:
            return value
    if kind in (PROPERTY, PROPERTY_VALUE) and prop in config.PERCEPTION_BOOLEAN_PROPERTIES:
        flag = _boolean(value)
        return value if flag is None else flag
    return value


def arguments_of(element):
    """The attributes of a node as typed arguments, without name (and memory)."""
    table = grammar().get(element.tag)
    if table is None:
        return {k: v for k, v in element.attrib.items() if k != 'name'}
    _, required, optional = table
    kinds = {**required, **optional}
    prop = element.attrib.get('property')
    result = {}
    for attribute, value in element.attrib.items():
        if attribute in ('name', 'memory'):
            continue
        kind = kinds.get(attribute)
        result[attribute] = typed(kind, value, prop if kind == PROPERTY_VALUE else attribute)
    return result


# --- The checks --------------------------------------------------------------------

def check_xml(text):
    """Run every check against one XML tree.

    Returns ``(checks, built_tree_or_None, root_element_or_None)``. The built tree is a
    real py_trees tree whose nodes carry their XML ``name`` and an ``arguments`` dict,
    so the graph and ``loop.outline_for_judge`` read it as before.
    """
    checks = []
    try:
        document, stray = read_xml(text)
    except XMLReadError as error:
        checks.append(Check('syntax.parse', 'The tree parses as XML', False,
                            f'{error.message} (line {error.line}, column {error.column})',
                            line=error.line, group='Syntax'))
        return checks, None, None
    checks.append(Check('syntax.parse', 'The tree parses as XML', True,
                        'well-formed XML', group='Syntax'))

    root, problems = _locate_root(document)
    checks.append(Check(
        'syntax.document', 'The document has the root and BehaviorTree frame',
        not problems,
        f'<root main_tree_to_execute="{MAIN_TREE_ID}"> holds one '
        f'<BehaviorTree ID="{MAIN_TREE_ID}"> with one root node'
        if not problems else '; '.join(problems),
        line=document.line if problems else None, group='Syntax'))
    checks.append(Check(
        'syntax.text', 'Nothing but tags between the tags', not stray,
        'no stray text' if not stray
        else 'text outside any attribute, which is ignored: ' + '; '.join(
            f'"{words[:40]}" (line {line})' for line, words in stray),
        line=stray[0][0] if stray else None, severity='warning', group='Syntax'))
    if root is None:
        return checks, None, None

    elements = list(root.walk())
    checks.extend(_check_structure(root, elements))
    checks.extend(_check_arguments(elements))
    checks.extend(_check_properties(elements))
    checks.extend(_check_references(elements))

    built = None
    if any(check.blocking for check in checks):
        checks.append(Check('build.parse', 'py_trees builds the tree', False,
                            'not built: fix the errors above first',
                            severity='warning', group='Build'))
    else:
        built, build_checks = _build(text, root)
        checks.extend(build_checks)
    return checks, built, root


def passed(checks):
    """True when no blocking check failed. Warnings never stop a run."""
    return not any(check.blocking for check in checks)


def _locate_root(document):
    """The root node of the tree, and what is wrong with the frame around it."""
    problems = []
    if document.tag != 'root':
        problems.append(f'the document element is <{document.tag}>, not <root>')
    if document.attrib.get('main_tree_to_execute') != MAIN_TREE_ID:
        problems.append(f'<root> needs main_tree_to_execute="{MAIN_TREE_ID}"')
    extra = sorted(set(document.attrib) - {'main_tree_to_execute', 'BTCPP_format'})
    if extra:
        problems.append(f'<root> does not take {", ".join(extra)}')

    trees = [c for c in document.children if c.tag == 'BehaviorTree']
    others = [c for c in document.children if c.tag != 'BehaviorTree']
    if others:
        problems.append('<root> may hold only the BehaviorTree, not '
                        + ', '.join(f'<{c.tag}> (line {c.line})' for c in others))
    if len(trees) != 1:
        problems.append(f'<root> must hold exactly one <BehaviorTree>, it holds {len(trees)}')
        return None, problems

    tree = trees[0]
    if tree.attrib.get('ID') != MAIN_TREE_ID:
        problems.append(f'line {tree.line}: the BehaviorTree needs ID="{MAIN_TREE_ID}"')
    extra = sorted(set(tree.attrib) - {'ID'})
    if extra:
        problems.append(f'line {tree.line}: <BehaviorTree> does not take {", ".join(extra)}')
    if len(tree.children) != 1:
        problems.append(f'line {tree.line}: the BehaviorTree must hold exactly one node, '
                        f'the root Sequence; it holds {len(tree.children)}')
        return None, problems
    return tree.children[0], problems


def _check_structure(root, elements):
    checks = []
    table = grammar()

    correct_root = root.tag == 'Sequence' and root.name == 'Root'
    checks.append(Check(
        'structure.root_type', 'The root is a Sequence named "Root"', correct_root,
        'correct' if correct_root else f'the root is <{root.tag}> named "{root.name}"',
        line=root.line, group='Structure'))

    unknown = []
    for element, _ in elements:
        if element.tag in table:
            continue
        if element.tag in DECORATORS or element.tag in NOT_IN_GRAMMAR:
            hint = NOT_IN_GRAMMAR.get(element.tag, 'not one of the decorators the prompt names')
            unknown.append(f'<{element.tag}> (line {element.line}): {hint}')
        else:
            unknown.append(f'<{element.tag}> (line {element.line})')
    checks.append(Check(
        'structure.allowed_nodes', 'Only the nodes the prompt allows', not unknown,
        f'{len(elements)} nodes, all allowed' if not unknown
        else 'not allowed: ' + '; '.join(unknown),
        line=_first_line(unknown), group='Structure'))

    composites = [e for e, _ in elements if e.tag in COMPOSITES]
    wrong_memory = [e for e in composites
                    if 'memory' in e.attrib and e.attrib['memory'].lower() != 'true']
    checks.append(Check(
        'structure.memory', 'No Sequence or Selector turns memory off', not wrong_memory,
        f'all {len(composites)} composites keep memory' if not wrong_memory
        else 'memory must be "true" on: ' + ', '.join(
            f'{e.name or e.tag} (line {e.line}, memory="{e.attrib["memory"]}")'
            for e in wrong_memory),
        line=wrong_memory[0].line if wrong_memory else None, group='Structure'))
    unwritten = [e for e in composites if 'memory' not in e.attrib]
    checks.append(Check(
        'structure.memory_written', 'Every Sequence and Selector writes memory="true"',
        not unwritten,
        'all composites write it' if not unwritten
        else 'missing on (py_trees then uses true): ' + ', '.join(
            f'{e.name or e.tag} (line {e.line})' for e in unwritten),
        line=unwritten[0].line if unwritten else None, severity='warning',
        group='Structure'))

    wrong_children = []
    for element, _ in elements:
        kind = table.get(element.tag, (None,))[0]
        count = len(element.children)
        if kind == 'composite' and count == 0:
            wrong_children.append(f'{element.tag} "{element.name}" (line {element.line}) '
                                  f'has no children')
        elif kind == 'decorator' and count != 1:
            wrong_children.append(f'{element.tag} "{element.name}" (line {element.line}) '
                                  f'wraps {count} nodes; a decorator wraps exactly one')
        elif kind in ('action', 'find', 'condition') and count:
            wrong_children.append(f'{element.tag} "{element.name}" (line {element.line}) '
                                  f'has nodes inside it; close it with />')
    checks.append(Check(
        'structure.children', 'Every node has the right number of children',
        not wrong_children,
        'composites have children, decorators one, leaves none' if not wrong_children
        else '; '.join(wrong_children), line=_first_line(wrong_children), group='Structure'))

    names = [e.name for e, _ in elements if e.name]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    checks.append(Check(
        'structure.unique_names', 'Every node name is unique', not duplicates,
        f'{len(names)} distinct names' if not duplicates
        else 'used more than once: ' + ', '.join(duplicates), group='Structure'))

    not_pascal = [e for e, _ in elements if e.name and not e.name[:1].isupper()]
    checks.append(Check(
        'structure.name_style', 'Node names are PascalCase', not not_pascal,
        'all names start with a capital' if not not_pascal
        else 'not PascalCase: ' + ', '.join(f'"{e.name}"' for e in not_pascal),
        severity='warning', group='Structure'))

    wrong_inverters = []
    for element, _ in elements:
        if element.tag != 'Inverter' or len(element.children) != 1:
            continue        # a wrong number of children is reported above
        child = element.children[0]
        if child.tag not in CONDITIONS:
            wrong_inverters.append(
                f'{element.name or "Inverter"} on line {element.line} wraps {child.tag}; '
                f'an Inverter may only wrap HasProperty or HasCount, to mean "not"')
    checks.append(Check(
        'structure.inverter', 'An Inverter wraps only a condition', not wrong_inverters,
        'every Inverter wraps HasProperty or HasCount' if not wrong_inverters
        else '; '.join(wrong_inverters), line=_first_line(wrong_inverters),
        group='Structure'))
    return checks


def _check_arguments(elements):
    table = grammar()
    problems, bad_counts, bad_names = [], [], []
    with_arguments = 0
    for element, _ in elements:
        if not _NAME.match(element.name):
            shown = f'name="{element.name}"' if 'name' in element.attrib else 'no name'
            bad_names.append(f'{element.tag} on line {element.line} has {shown}')
        if element.tag not in table:
            continue
        with_arguments += 1
        _, required, optional = table[element.tag]
        given = set(element.attrib) - {'name'}
        missing = sorted(set(required) - given)
        unexpected = sorted(given - set(required) - set(optional))
        if missing:
            problems.append(f'{element.tag} on line {element.line} is missing '
                            f'{", ".join(missing)}')
        if unexpected:
            hint = (f' (properties: {", ".join(perception_properties())})'
                    if table[element.tag][0] == 'find' else '')
            problems.append(f'{element.tag} on line {element.line} does not take '
                            f'{", ".join(unexpected)}{hint}')
        for attribute, kind in {**required, **optional}.items():
            if attribute not in element.attrib or attribute in ('nth', 'limit', 'count'):
                continue        # nth, limit and count are checked with the objects
            value = element.attrib[attribute]
            if kind == POSITIVE and (_integer(value) or 0) < 1:
                bad_counts.append(f'line {element.line}: {attribute}="{value}" is not a '
                                  f'whole number of 1 or more')
            elif kind == SECONDS and not _positive_number(value):
                bad_counts.append(f'line {element.line}: {attribute}="{value}" is not a '
                                  f'number of seconds above 0')

    return [
        Check('arguments.signatures', 'Every node gets exactly its own arguments',
              not problems,
              f'{with_arguments} nodes are correct' if not problems else '; '.join(problems),
              line=_first_line(problems), group='Arguments'),
        Check('arguments.counts', 'Counts are whole numbers', not bad_counts,
              'all counts are whole numbers' if not bad_counts else '; '.join(bad_counts),
              line=_first_line(bad_counts), group='Arguments'),
        Check('arguments.names', 'Every node has a name of letters and digits',
              not bad_names,
              'all nodes are named' if not bad_names else '; '.join(bad_names),
              line=_first_line(bad_names), group='Arguments'),
    ]


def _check_properties(elements):
    """Every property and value a find or check node uses must be one the robot has."""
    problems = []
    for element, _ in elements:
        attrib, where = element.attrib, f'line {element.line}'
        if element.tag in ('FindOne', 'FindAll'):
            for prop in perception_properties():
                if prop in attrib:
                    problems.extend(_property_problem(where, prop, attrib[prop]))
            if 'position' in attrib and attrib['position'] not in config.FIND_POSITIONS:
                problems.append(f'{where}: position="{attrib["position"]}" is not one of '
                                f'{", ".join(config.FIND_POSITIONS)}')
            counted = 'nth' if element.tag == 'FindOne' else 'limit'
            if counted in attrib and (_integer(attrib[counted]) or 0) < 1:
                problems.append(f'{where}: {counted}="{attrib[counted]}" is not a whole '
                                f'number of 1 or more')
        elif element.tag == 'HasCount':
            if 'count' in attrib and _integer(attrib['count']) is None:
                problems.append(f'{where}: count="{attrib["count"]}" is not a whole number '
                                f'of 0 or more')
            if 'comparison' in attrib and \
                    attrib['comparison'] not in config.HAS_COUNT_COMPARISONS:
                problems.append(f'{where}: comparison="{attrib["comparison"]}" is not one of '
                                f'{", ".join(config.HAS_COUNT_COMPARISONS)}')
        elif element.tag == 'HasProperty' and 'property' in attrib:
            prop = attrib['property']
            if prop not in perception_properties():
                problems.append(f'{where}: property="{prop}" is not one of '
                                f'{", ".join(perception_properties())}')
            elif 'value' in attrib:
                problems.extend(_property_problem(where, prop, attrib['value'], 'value'))
    return [Check(
        'objects.properties', 'Objects are described with properties the robot has',
        not problems,
        'every property and value is one the robot perceives' if not problems
        else '; '.join(problems), line=_first_line(problems), group='Objects')]


def _property_problem(where, prop, value, attribute=None):
    shown = f'{where}: {attribute or prop}="{value}"'
    if prop == 'type':
        if value not in config.PERCEPTION_TYPES:
            return [f'{shown} is not a type the robot perceives '
                    f'({", ".join(config.PERCEPTION_TYPES)})']
    elif prop in config.PERCEPTION_COLOR_PROPERTIES:
        if value != value.lower() or '{' in value:
            return [f'{shown} must be a lowercase colour name']
    elif _boolean(value) is None:
        return [f'{shown} must be True or False']
    return []


def _check_references(elements):
    """Keys are stored once and used the way they were stored, and every object
    argument is a {key} reference to something stored earlier."""
    table = grammar()
    order = {id(element): index for index, (element, _) in enumerate(elements)}
    parents = {id(element): parent for element, parent in elements}
    stored, key_problems, reference_problems = {}, [], []

    # What each key holds: one object (FindOne), a list (FindAll), or the current item of
    # a loop (the target_key of a ForEach, usable inside that loop only).
    for element, _ in elements:
        if element.tag not in table:
            continue
        for attribute, kind in table[element.tag][1].items():
            if kind not in (STORE, TARGET) or attribute not in element.attrib:
                continue
            key = element.attrib[attribute]
            where = f'line {element.line}: {attribute}="{key}"'
            if _REFERENCE.match(key) or key.startswith('@'):
                key_problems.append(f'{where} is where a key is stored; write the plain '
                                    f'name "{key.strip("{}@")}", without braces')
            elif not _PLAIN_KEY.match(key):
                key_problems.append(f'{where} is not a plain name of letters, digits and _')
            elif key in stored:
                key_problems.append(f'{where}: "{key}" is already stored on line '
                                    f'{stored[key][0].line}; every key is stored once')
            else:
                holds = ('item' if kind == TARGET
                         else 'list' if element.tag == 'FindAll' else 'object')
                stored[key] = (element, holds)

    def use(element, attribute, value, wanted):
        where = f'line {element.line}: {attribute}="{value}"'
        if wanted == 'list':
            if _REFERENCE.match(value) or value.startswith('@'):
                reference_problems.append(f'{where} names a list; write the plain name '
                                          f'"{value.strip("{}@")}", without braces')
                return
            key = value
        else:
            match = _REFERENCE.match(value)
            if match:
                key = match.group(1)
            elif value.startswith('@'):
                reference_problems.append(f'{where}: write the reference in curly braces, '
                                          f'"{{{value[1:]}}}"')
                return
            else:
                reference_problems.append(f'{where} is not a reference; refer to an object a '
                                          f'find node stored, as "{{key}}"')
                return
        if key not in stored:
            reference_problems.append(f'{where}: no node stores "{key}"')
            return
        owner, holds = stored[key]
        if holds == 'item':
            ancestor, inside = parents[id(element)], False
            while ancestor is not None:
                inside = inside or ancestor is owner
                ancestor = parents[id(ancestor)]
            if not inside:
                reference_problems.append(f'{where}: "{key}" is the target of the ForEach on '
                                          f'line {owner.line} and can only be used inside it')
            elif wanted == 'list':
                reference_problems.append(
                    f'{where}: "{key}" is one item of the ForEach on line {owner.line}, not '
                    f'a list; ' + ('count the list the ForEach loops over'
                                   if element.tag == 'HasCount' else 'loop over a FindAll list'))
            return
        if order[id(owner)] > order[id(element)]:
            reference_problems.append(f'{where}: "{key}" is stored on line {owner.line}, '
                                      f'after this node runs')
        elif holds != wanted:
            reference_problems.append(
                f'{where}: "{key}" holds a list (FindAll); loop over it with ForEach and use '
                f'the loop\'s target' if holds == 'list' else
                f'{where}: "{key}" holds one object (FindOne), not a list'
                + ('; HasCount counts the list of a FindAll'
                   if element.tag == 'HasCount' else ''))

    for element, _ in elements:
        if element.tag not in table:
            continue
        _, required, optional = table[element.tag]
        for attribute, kind in {**required, **optional}.items():
            if attribute not in element.attrib:
                continue
            if kind == OBJECT:
                use(element, attribute, element.attrib[attribute], 'object')
            elif kind == LIST:
                use(element, attribute, element.attrib[attribute], 'list')
        # Braces mean "blackboard entry" to the parser, wherever they appear.
        for attribute, value in element.attrib.items():
            kind = {**required, **optional}.get(attribute)
            if kind not in (OBJECT, LIST, STORE, TARGET) and '{' in value:
                reference_problems.append(
                    f'line {element.line}: {attribute}="{value}" may not use curly braces; '
                    f'they are only for object references')

    return [
        Check('objects.keys', 'Every key is a plain name that is stored once',
              not key_problems,
              f'{len(stored)} keys' if not key_problems else '; '.join(key_problems),
              line=_first_line(key_problems), group='Objects'),
        Check('objects.references', 'Every object is a {key} stored before it is used',
              not reference_problems,
              'every reference points at an object found earlier'
              if not reference_problems else '; '.join(reference_problems),
              line=_first_line(reference_problems), group='Objects')]


# --- Building ----------------------------------------------------------------------

def _build(text, root):
    """Hand the document to the py_trees parser, then label the nodes for display."""
    try:
        from py_trees.parsers.behaviour_tree_xml import parse_behaviour_tree_xml

        from modules import bt_nodes
    except ImportError as error:
        return None, [Check('build.py_trees', 'py_trees 2.6 or later is installed', False,
                            f'{error} — install it with: pip install "py_trees>=2.6"',
                            group='Build')]

    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / 'tree.xml'
        path.write_text(text, encoding='utf-8')
        try:
            built = parse_behaviour_tree_xml(str(path), node_registry=bt_nodes.REGISTRY)
        except Exception as error:  # noqa: BLE001 - every parser error is a failed build
            return None, [Check('build.parse', 'py_trees builds the tree', False,
                                f'{type(error).__name__}: {error}', group='Build')]

    checks = [Check('build.parse', 'py_trees builds the tree', True,
                    f'{type(built).__name__}(name="{root.name}")', group='Build')]
    built_nodes = sum(1 for _ in built.iterate())
    declared = sum(1 for _ in root.walk())
    matches = built_nodes == declared and _label(built, root)
    checks.append(Check(
        'build.node_count', 'Every node in the XML is in the built tree', matches,
        f'{built_nodes} nodes' if matches
        else f'{declared} nodes were written but the built tree has {built_nodes}',
        group='Build'))
    return (built if matches else None), checks


def _label(node, element):
    """Give every built node its XML name and arguments; False if the shapes differ.

    The parser prefixes each name with its parents' names (Root.ForEachTube.PlaceTube);
    the graph, the judge outline and the run folder show the name the generator wrote.
    Node names are unique (checked above), so nothing is lost.
    """
    if type(node).__name__ != element.tag:
        return False
    children = list(getattr(node, 'children', []))
    if len(children) != len(element.children):
        return False
    node.name = element.name
    node.arguments = arguments_of(element)
    return all(_label(child, child_element)
               for child, child_element in zip(children, element.children))


# --- Small helpers -----------------------------------------------------------------

def _first_line(messages):
    for message in messages:
        match = re.search(r'line (\d+)', message)
        if match:
            return int(match.group(1))
    return None


def _positive_number(value):
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False
