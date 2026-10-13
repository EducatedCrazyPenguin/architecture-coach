"""Learning views read immutable records; no target code or provider is executed."""
import ast
import difflib
from .capture import read_blob
from .models import Evidence


def saved_excerpt(settings, snapshot, evidence):
    try:
        ref = Evidence.model_validate(evidence)
        if not ref.valid:
            return None
        entry = next(item for item in snapshot['manifest'] if item['path'] == ref.path)
        lines = read_blob(settings, entry['sha256']).decode('utf-8', errors='replace').splitlines()
        end = ref.end_line or ref.line
        if end > len(lines):
            return None
        shown_end = min(end, ref.line + 39)
        code = '\n'.join(lines[ref.line - 1:shown_end])
        return {'path': ref.path, 'line': ref.line, 'end_line': shown_end, 'code': code[:6000],
                'truncated': shown_end < end or len(code) > 6000}
    except (ValueError, KeyError, StopIteration, OSError):
        return None


def lesson_examples(settings, snapshot, critique):
    return {lesson['id']: [example for ref in lesson.get('evidence', [])
                           if (example := saved_excerpt(settings, snapshot, ref))]
            for lesson in critique.get('lessons', [])}


PRACTICE_GUIDANCE = {
    'answer': 'Answer the learner question using saved evidence.',
    'hint': 'Give one small reading hint pointing to cited code. Do not reveal the correct option, full solution or expected answer.',
    'simpler': 'Assume the learner is new to Python and to reading code. Use plain language before code: explain what the part does, what goes in and what comes out with one concrete everyday example grounded in saved source. Teach one idea at a time; define each term before using it. Avoid unexplained words such as truthy, signature, dependency injection or serialization. Show at most three relevant code lines only after explaining the idea. Keep it under 180 words and finish with one short question in plain language, not bundled homework. Do not invent infrastructure; qualify static predictions.',
    'deeper': 'Explain dependency direction, assumptions, failure paths and tradeoffs only where the saved source supports them. Identify unknowns.',
    'explain_back': 'Use this explicit rubric: Correct points; Missing or mistaken reasoning; One next question. Compare the learner explanation with the saved expected reasoning and cited code. Accept equivalent wording. Assess code understanding, never language fluency. Cite corrections; say uncertain when source is insufficient.',
    'design': 'Frame the requested change as hypothetical. State input/output behavior to preserve and assumptions. Allow multiple defensible designs. Discuss at least two alternatives and their costs when supported. Each proposed valid alternative must satisfy all mandatory constraints. If names or other data must survive restart, identify concrete durable storage and recovery for every valid alternative; dependency injection or an in-memory object alone does not provide durability. Label an option that fails a constraint as rejected, never as a valid alternative. Existing tests are captured, not executed. Do not grade an alternative wrong merely because it differs from your preference.',
}


def practice_context(settings, snapshot, review, mode, question_id, attempt=None):
    if mode not in PRACTICE_GUIDANCE:
        raise ValueError('Unknown instructor mode')
    question = None
    if question_id is not None:
        question = next((q for q in review['critique'].get('quiz', []) if q['id'] == question_id), None)
        if question is None:
            raise ValueError('Question not found in this saved review')
    context = {'format_version': 1, 'mode': mode, 'question_id': question_id,
               'question': question, 'attempt': attempt,
               'saved_examples': [example for ref in (question or {}).get('evidence', [])
                                  if (example := saved_excerpt(settings, snapshot, ref))]}
    if mode == 'hint' and question:
        context['question'] = {key: value for key, value in question.items() if key not in {'correct_index', 'explanations'}}
        context['attempt'] = None
    return PRACTICE_GUIDANCE[mode], context


def source_walkthroughs(settings, snapshot, review):
    """Source order is a reading aid, not a runtime or universally resolved call graph."""
    membership = {}
    for component in review['architecture']['components']:
        for path in (component.get('source_paths') or [r['path'] for r in component.get('sources', [])]):
            membership.setdefault(path, set()).add(component['id'])
    owners = {path: next(iter(ids)) for path, ids in membership.items() if len(ids) == 1}
    python_files = [f for f in snapshot['manifest'] if f['path'].lower().endswith('.py')]
    notes, trees, outlines = [], {}, []
    notes.extend(f'{path}: component ownership is ambiguous; no graph component is selected.' for path, ids in sorted(membership.items()) if len(ids) > 1)
    for item in sorted(python_files, key=lambda f: (f['path'] not in owners, f['path']))[:24]:
        path = item['path']
        try:
            content = read_blob(settings, item['sha256']).decode('utf-8', errors='replace')
            if len(content) > 100_000:
                notes.append(f'{path}: omitted from walkthrough parsing (size limit).'); continue
            trees[path] = ast.parse(content)
        except (SyntaxError, OSError, ValueError, RecursionError) as exc:
            notes.append(f'{path}: walkthrough parser unavailable ({type(exc).__name__}).')
    if len(python_files) > 24:
        notes.append(f'{len(python_files)-24} Python files outside the walkthrough parsing limit.')

    def body_nodes(node):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                continue
            yield child
            yield from body_nodes(child)

    from .analyze import _module_index, _resolve_python
    aliases, primary = _module_index(snapshot['manifest'])
    functions = {path: {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and sum(isinstance(other, (ast.FunctionDef, ast.AsyncFunctionDef)) and other.name == n.name for other in tree.body) == 1}
                 for path, tree in trees.items()}
    bindings = {}
    for path, tree in trees.items():
        local = {}
        for node in tree.body:
            if not isinstance(node, (ast.Import, ast.ImportFrom)) or path not in primary:
                continue
            resolved = _resolve_python(path, primary[path], node, aliases)
            for alias in node.names:
                if isinstance(node, ast.Import):
                    match = next((r for r in resolved if r['specifier'] == alias.name and r['status'] == 'local'), None)
                    if match:
                        local[alias.asname or alias.name] = (match['target'], None)
                elif alias.name != '*':
                    match = next((r for r in resolved if r['status'] == 'local' and r['target'] in functions and alias.name in functions[r['target']]), None)
                    if match:
                        local[alias.asname or alias.name] = (match['target'], alias.name)
        bindings[path] = local

    for path, table in functions.items():
        if _is_test(path):
            continue
        for function in sorted(table.values(), key=lambda n: (n.name not in {'main', 'run'}, n.lineno))[:4]:
            if len(outlines) >= 12:
                break
            steps, visited = [], set()
            def add(node, node_path, title, explanation, inferred=False, from_component=None):
                example = saved_excerpt(settings, snapshot, {'path': node_path, 'line': node.lineno, 'end_line': getattr(node, 'end_lineno', node.lineno)})
                if example and len(steps) < 30:
                    steps.append({'title': title, 'explanation': explanation, 'inferred': inferred,
                                  'component_id': owners.get(node_path), 'from_component_id': from_component, 'example': example})

            def follow(fn, fn_path, depth=0, from_component=None):
                key = (fn_path, fn.name)
                if key in visited or depth > 2 or len(steps) >= 30:
                    return
                visited.add(key)
                args = [arg.arg for arg in [*fn.args.posonlyargs, *fn.args.args, *fn.args.kwonlyargs]]
                args.extend(arg.arg for arg in (fn.args.vararg, fn.args.kwarg) if arg is not None)
                add(fn, fn_path, f'Boundary: {fn.name}', f'Declared parameters: {", ".join(args) or "none"}. Types and actual caller values are unconfirmed.', depth > 0, from_component)
                nodes = sorted(body_nodes(fn), key=lambda n: (getattr(n, 'lineno', 0), isinstance(n, ast.Return), getattr(n, 'col_offset', 0)))
                shadowed = set(args) | {n.id for n in nodes if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
                interesting = [n for n in nodes if isinstance(n, (ast.Call, ast.If, ast.Raise, ast.ExceptHandler, ast.Return))]
                for node in interesting[:10]:
                    if isinstance(node, ast.Call):
                        expression = ast.unparse(node.func)[:120]
                        target = None
                        if isinstance(node.func, ast.Name) and node.func.id not in shadowed:
                            name = node.func.id
                            target = (fn_path, name) if name in functions[fn_path] else bindings[fn_path].get(name)
                        elif isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id not in shadowed:
                            bound = bindings[fn_path].get(node.func.value.id)
                            if bound and bound[1] is None:
                                target = (bound[0], node.func.attr)
                        target_fn = functions.get(target[0], {}).get(target[1]) if target else None
                        detail = 'A unique captured declaration is linked below; runtime binding and branch remain inferred.' if target_fn else 'Target unresolved (external, dynamic, shadowed or outside the parsing budget).'
                        add(node, fn_path, 'Call site', f'Expression calls {expression}. {detail}', True)
                        if target_fn:
                            follow(target_fn, target[0], depth + 1, owners.get(fn_path))
                    elif isinstance(node, ast.If):
                        add(node, fn_path, 'Decision branch', 'Read the condition and both alternatives. Which branch runs depends on input.', True)
                    elif isinstance(node, (ast.Raise, ast.ExceptHandler)):
                        add(node, fn_path, 'Failure handling', 'Captured source declares this raise or handler. Whether it is reached and what callers observe needs separate evidence.', True)
                    else:
                        add(node, fn_path, 'Output boundary', 'This return declares an output expression. Its runtime value is unconfirmed.', True)
                if len(interesting) > 10 or len(steps) >= 30:
                    notes.append(f'{fn_path}:{fn.name}: additional constructs omitted from the bounded outline.')
            follow(function, path)
            tests = []
            for test_path, test_tree in trees.items():
                if not _is_test(test_path):
                    continue
                for assertion in [n for n in ast.walk(test_tree) if isinstance(n, ast.Assert)][:50]:
                    if any(isinstance(n, ast.Name) and n.id == function.name for n in ast.walk(assertion)):
                        example = saved_excerpt(settings, snapshot, {'path': test_path, 'line': assertion.lineno, 'end_line': assertion.end_lineno})
                        if example and len(tests) < 5:
                            tests.append(example)
            if steps:
                outlines.append({'id': f'{path}:{function.lineno}', 'name': f'{path} · {function.name}', 'steps': steps, 'tests': tests})
    if not outlines:
        notes.append('No supported Python function outline is available. JavaScript/TypeScript and DAZ feature tracing are limited; the dependency map and saved code remain available.')
    elif any(f['path'].lower().endswith(('.js', '.jsx', '.ts', '.tsx', '.dsa', '.ds')) for f in snapshot['manifest']):
        notes.append('JavaScript/TypeScript and DAZ functions are outside this Python walkthrough parser. Their dependency maps and saved files remain available.')
    return {'format_version': 1, 'review_id': review['id'], 'outlines': outlines, 'notes': list(dict.fromkeys(notes)),
            'qualification': 'Static reading outline; not an observed runtime trace. Local top-level declarations only; depth two, 30 steps per outline. Dynamic targets and omitted files remain unresolved. Test association is a name match, not proof of coverage or passing tests.'}


def _is_test(path):
    return any(part in {'test', 'tests'} or part.startswith('test_') or part.endswith('_test.py')
               for part in path.split('/'))


def change_examples(settings, before, before_snapshot, after, after_snapshot, changes):
    """Qualified change exercises; architecture deltas still belong to the common engine."""
    paths = sorted(set(changes['files_changed'] + changes['files_added'] + changes['files_removed']))
    old = {f['path']: f for f in before_snapshot['manifest']}
    new = {f['path']: f for f in after_snapshot['manifest']}
    items = []
    for path in paths[:12]:
        def lines(entries):
            if path not in entries:
                return []
            try:
                return read_blob(settings, entries[path]['sha256']).decode('utf-8', errors='replace').splitlines()
            except (OSError, ValueError):
                return []
        left, right = lines(old), lines(new)
        op = next((op for op in difflib.SequenceMatcher(None, left, right, autojunk=True).get_opcodes() if op[0] != 'equal'), None)
        ranges = (op[1:3], op[3:5]) if op else ((0, min(20, len(left))), (0, min(20, len(right))))
        examples = []
        for snapshot, content, (start, end) in zip((before_snapshot, after_snapshot), (left, right), ranges):
            ref = {'path': path, 'line': max(1, start - 2), 'end_line': min(len(content), max(end + 2, start + 1))}
            examples.append(saved_excerpt(settings, snapshot, ref) if content else None)
        callers = []
        for review in (before, after):
            arch = review['architecture']
            names = {c['id']: c['name'] for c in arch['components']}
            owners = {c['id'] for c in arch['components'] if path in (c.get('source_paths') or [r['path'] for r in c.get('sources', [])])}
            for edge in arch['relationships']:
                if edge['target'] in owners:
                    callers.append({'review_id': review['id'], 'name': names[edge['source']], 'kind': edge.get('kind', 'dependency'), 'inferred': edge.get('inferred', False)})
        items.append({'path': path, 'before': examples[0], 'after': examples[1], 'callers': callers})
    return {'items': items, 'omitted': max(0, len(paths) - 12)}


def concept_examples(settings, snapshot, review, concept):
    examples = []
    for question in review['critique'].get('quiz', []):
        if question.get('concept', 'unclassified') != concept:
            continue
        excerpts = [item for ref in question.get('evidence', []) if (item := saved_excerpt(settings, snapshot, ref))]
        if excerpts:
            examples.append({'question': question, 'excerpts': excerpts})
    return examples[:3]
