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
    'answer': 'Assume a beginner. Start with the selected part\'s job, then one concrete example from saved evidence. Teach one idea at a time and define technical terms when introduced. Keep code optional. Separate captured code from hypothetical illustrations; declare assumptions about outputs and failures. Answer the learner question, identifying what the saved source cannot establish.',
    'hint': 'Give one small reading hint pointing to cited code. Do not reveal the correct option, full solution or expected answer.',
    'simpler': 'Assume the learner is new to Python and to reading code. Use plain language before code: explain what the part does, what goes in and what comes out with one concrete everyday example grounded in saved source. Teach one idea at a time; define each term before using it. Avoid unexplained words such as truthy, signature, dependency injection or serialization. Show at most three relevant code lines only after explaining the idea. Keep it under 180 words and finish with one short question in plain language, not bundled homework. Do not invent infrastructure; qualify static predictions.',
    'deeper': 'Explain dependency direction, assumptions, failure paths and tradeoffs only where the saved source supports them. Identify unknowns.',
    'explain_back': 'Use this explicit rubric: Correct points; Missing or mistaken reasoning; One next question. Return correct_points, missing_reasoning, next_question and citations in the supplied feedback schema. Use plain words; define necessary code terms. Ask exactly one short follow-up question. Compare the learner explanation with the saved expected reasoning and cited code. Accept equivalent wording. Assess code understanding, never language fluency. Cite corrections; say uncertain when source is insufficient.',
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


def check_teaching_claims(settings, snapshot, response):
    """Narrow deterministic checks, not a general correctness or runtime verifier."""
    import re
    import tomllib
    if re.search(r'(?im)^\s*(?:all|the|these) tests (?:passed|have passed|are passing)\b', response.answer):
        raise ValueError('A source-only instructor cannot claim tests passed')
    entries = {f['path']:f for f in snapshot['manifest']}
    contents = {ref.path:read_blob(settings,entries[ref.path]['sha256']).decode('utf-8',errors='replace') for ref in response.citations}
    for quote in re.findall(r'(?im)^(?:saved|captured) code:\s*\n```[^\n]*\n(.*?)\n```',response.answer,re.S):
        if not any(quote.strip() in text for text in contents.values()):
            raise ValueError('An alleged saved quotation differs from its cited source; label alternatives hypothetical')
    trees = {}
    for path,text in contents.items():
        if not path.endswith('.py') or len(text)>100_000: continue
        try: trees[path]=ast.parse(text)
        except (SyntaxError,ValueError,RecursionError): continue
    if trees and re.search(r'(?im)^\s*(?:the function )?main(?:\(\))? is (?:the )?(?:CLI|command.line) entry ?point\b',response.answer):
        guarded=any(isinstance(node,ast.If) and ast.unparse(node.test) in {"__name__ == '__main__'","'__main__' == __name__"} and any(isinstance(c,ast.Call) and isinstance(c.func,ast.Name) and c.func.id=='main' for stmt in node.body for c in ast.walk(stmt)) for tree in trees.values() for node in tree.body)
        configured=False
        from .analyze import _python_aliases
        for entry in snapshot['manifest']:
            if not entry['path'].endswith('pyproject.toml'): continue
            try: scripts=tomllib.loads(read_blob(settings,entry['sha256']).decode()).get('project',{}).get('scripts',{})
            except (ValueError,UnicodeError): continue
            configured |= any(isinstance(target,str) and target.partition(':')[2].strip()=='main' and any(target.partition(':')[0] in _python_aliases(path) for path in trees) for target in scripts.values())
        if not guarded and not configured: raise ValueError('The name main alone does not establish a command-line entry point')
    if re.search(r'(?im)^\s*the empty check rejects whitespace.only (?:names|strings)\b',response.answer):
        for tree in trees.values():
            for function in [n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))]:
                parameters={a.arg for a in function.args.args}
                for node in ast.walk(function):
                    if not (isinstance(node,ast.If) and isinstance(node.test,ast.UnaryOp) and isinstance(node.test.op,ast.Not) and isinstance(node.test.operand,ast.Name)): continue
                    name=node.test.operand.id
                    assigned=any(isinstance(n,ast.Name) and isinstance(n.ctx,ast.Store) and n.id==name and n.lineno<node.lineno for n in ast.walk(function))
                    if name in parameters and not assigned:
                        raise ValueError('A raw not-name check does not reject a nonempty string of spaces; inspect separate stripping and checks')


def _python_walkthroughs(settings, snapshot, review, selected_path=None, cancelled=lambda: False):
    """Source order is a reading aid, not a runtime or universally resolved call graph."""
    membership = {}
    for component in review['architecture']['components']:
        for path in (component.get('source_paths') or [r['path'] for r in component.get('sources', [])]):
            membership.setdefault(path, set()).add(component['id'])
    owners = {path: next(iter(ids)) for path, ids in membership.items() if len(ids) == 1}
    python_files = [f for f in snapshot['manifest'] if f['path'].lower().endswith('.py')]
    notes, trees, outlines = [], {}, []
    notes.extend(f'{path}: component ownership is ambiguous; no graph component is selected.' for path, ids in sorted(membership.items()) if len(ids) > 1)
    for item in sorted(python_files, key=lambda f: (f['path'] != selected_path, f['path'] not in owners, f['path']))[:24]:
        if cancelled():
            from .subprocesses import ProcessCancelled
            raise ProcessCancelled('Reading outline cancelled')
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

    def body_nodes(node, branch='', include=False):
        if include and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            return
        node._reading_branch = branch
        if include and isinstance(node, (ast.If, ast.IfExp)):
            yield from body_nodes(node.test, branch, True)
            yield node
            condition = ast.unparse(node.test)[:100]
            for statements, label in ((node.body, 'true'), (node.orelse, 'false')):
                for statement in statements if isinstance(statements, list) else [statements]:
                    yield from body_nodes(statement, f'If {condition} is {label}', True)
                    if isinstance(statement, (ast.Raise, ast.Return)): break
            return
        if isinstance(node, ast.ExceptHandler):
            branch = 'If a matching exception is handled'
            node._reading_branch = branch
        for child in ast.iter_child_nodes(node):
            yield from body_nodes(child, branch, True)
            if isinstance(child, (ast.Raise, ast.Return)):
                break
        if include:
            yield node

    from .analyze import _module_index, _resolve_python
    aliases, primary = _module_index(snapshot['manifest'])
    functions = {path: {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and sum(isinstance(other, (ast.FunctionDef, ast.AsyncFunctionDef)) and other.name == n.name for other in tree.body) == 1}
                 for path, tree in trees.items()}
    bindings, module_writes = {}, {}
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
        module_writes[path] = {n.id for statement in tree.body if not isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) for n in ast.walk(statement) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}

    for path, table in functions.items():
        if _is_test(path):
            continue
        for function in sorted(table.values(), key=lambda n: (n.name not in {'main', 'run'}, n.lineno))[:4]:
            if len(outlines) >= 12:
                break
            steps, visited = [], set()
            def add(node, node_path, title, explanation, inferred=False, from_component=None):
                branch = getattr(node, '_reading_branch', '')
                if branch: explanation = f'{branch}. {explanation}'
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
                nodes = []
                for statement in fn.body:
                    nodes.extend(body_nodes(statement, include=True))
                    if isinstance(statement, (ast.Raise, ast.Return)): break
                shadowed = set(args) | module_writes[fn_path] | {n.id for n in nodes if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
                interesting = [n for n in nodes if isinstance(n, (ast.Call, ast.If, ast.IfExp, ast.Raise, ast.ExceptHandler, ast.Return, ast.Assign, ast.AugAssign))]
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
                    elif isinstance(node, (ast.If, ast.IfExp)):
                        add(node, fn_path, 'Decision branch', 'Read the condition and both alternatives. Which branch runs depends on input.', True)
                    elif isinstance(node, (ast.Raise, ast.ExceptHandler)):
                        add(node, fn_path, 'Failure handling', 'Captured source declares this raise or handler. Whether it is reached and what callers observe needs separate evidence.', True)
                    elif isinstance(node, (ast.Assign, ast.AugAssign)):
                        add(node, fn_path, 'State or local value', 'This statement stores a value. A local value is not necessarily durable state; inspect the declared target.', True)
                    else:
                        add(node, fn_path, 'Output boundary', 'If this point is reached, the evaluated expression is returned. An uncaught exception stops this path; the output value is unobserved.', True)
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
                entry = 'Declared function; how it is called is unconfirmed'
                for node in trees[path].body:
                    if isinstance(node, ast.If) and ast.unparse(node.test) in {"__name__ == '__main__'", "'__main__' == __name__"}:
                        if any(isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == function.name for statement in node.body for call in ast.walk(statement)):
                            entry = 'Called from the captured Python script guard'
                decorators = [ast.unparse(d) for d in function.decorator_list]
                if any(d.split('(')[0].rsplit('.', 1)[-1] in {'get', 'post', 'put', 'delete', 'patch', 'route'} for d in decorators):
                    entry = 'Declared route decorator; framework binding is inferred'
                outlines.append({'id': f'{path}:{function.lineno}', 'name': f'{path} · {function.name}', 'entry': entry, 'steps': steps, 'tests': tests})
    if not outlines:
        notes.append('No supported Python function outline is available. JavaScript/TypeScript and DAZ feature tracing are limited; the dependency map and saved code remain available.')
    elif any(f['path'].lower().endswith(('.js', '.jsx', '.ts', '.tsx', '.dsa', '.ds')) for f in snapshot['manifest']):
        notes.append('JavaScript/TypeScript and DAZ functions are outside this Python walkthrough parser. Their dependency maps and saved files remain available.')
    return {'format_version': 1, 'review_id': review['id'], 'outlines': outlines, 'notes': list(dict.fromkeys(notes)),
            'qualification': 'Static reading outline; not an observed runtime trace. Local top-level declarations only; depth two, 30 steps per outline. Dynamic targets and omitted files remain unresolved. Test association is a name match, not proof of coverage or passing tests.'}


def source_walkthroughs(settings, snapshot, review, selected_path=None, cancelled=lambda: False):
    """Version two adds compiler-backed outlines without rewriting captured analysis."""
    from .workspace import source_role
    from .analyze import _typescript_analysis
    supported = [f for f in snapshot['manifest'] if f['path'].lower().endswith(('.py', '.js', '.jsx', '.ts', '.tsx', '.mjs', '.cjs'))]
    if selected_path and selected_path not in {f['path'] for f in supported}: raise ValueError('Selected file is outside supported saved source')
    neighbours = {e['target'] for e in snapshot['analysis'].get('edges', []) if e['source']==selected_path} | {e['source'] for e in snapshot['analysis'].get('edges', []) if e['target']==selected_path}
    supported.sort(key=lambda f: (f['path'] != selected_path, f['path'] not in neighbours, source_role(f['path']) == 'tests', f['path']))
    chosen = supported[:24]
    bounded = {**snapshot, 'manifest': chosen}
    result = _python_walkthroughs(settings, bounded, review, selected_path, cancelled)
    result['format_version'] = 2
    result['notes'] = [n for n in result['notes'] if 'JavaScript/TypeScript' not in n and 'No supported Python' not in n]
    if len(supported) > 24: result['notes'].append(f'{len(supported)-24} files outside the shared 24-file parsing budget.')
    typed_files = [f for f in chosen if not f['path'].lower().endswith('.py')]
    if typed_files:
        configs = [f for f in snapshot['manifest'] if f['path'].lower().endswith('.json')]
        rows, error = _typescript_analysis(settings, [*typed_files, *configs], cancelled)
        if error: result['notes'].append(error)
        membership = {f['path']: [c['id'] for c in review['architecture']['components'] if f['path'] in (c.get('source_paths') or [r['path'] for r in c.get('sources', [])])] for f in chosen}
        def steps_for(path, outline, depth=0, visited=None):
            visited = set() if visited is None else set(visited)
            key = (path, outline['name'])
            if key in visited or depth > 2: return []
            visited.add(key); steps = []
            for step in outline['steps']:
                example = saved_excerpt(settings, snapshot, {'path': path, 'line': step['line'], 'end_line': step['end_line']})
                if not example: continue
                ids = membership.get(path, [])
                steps.append({**step, 'example': example, 'component_id': ids[0] if len(ids)==1 else None, 'from_component_id':None})
                target = step.get('target')
                if target and target['path'] in rows:
                    matches = [f for f in rows[target['path']].get('outlines', []) if f['name']==target['name'] and (target['path']==path or f['exported'])]
                    if len(matches)==1: steps.extend(steps_for(target['path'], matches[0], depth+1, visited))
                if len(steps)>=30: break
            return steps[:30]
        for path, row in rows.items():
            result['notes'].extend(f'{path}: {issue}' for issue in row.get('configuration_issues', []))
            result['notes'].extend(f'{path}: {issue}' for issue in row.get('diagnostics', []))
            if source_role(path) == 'tests': continue
            for outline in row.get('outlines', []):
                steps = steps_for(path, outline)
                if steps: result['outlines'].append({'id':f"{path}:{outline['line']}", 'name':f"{path} · {outline['name']}", 'entry':outline['entry'], 'steps':steps, 'tests':[]})
    for outline in result['outlines']:
        outline.setdefault('entry', 'Declared Python function; entry mechanism unconfirmed')
    result['outlines'].sort(key=lambda o:o['id'].rsplit(':',1)[0] != selected_path)
    if len(result['outlines'])>12: result['notes'].append(f"{len(result['outlines'])-12} additional function outlines omitted; select a narrower saved file.")
    result['outlines']=result['outlines'][:12]
    result['selected_path']=selected_path
    if any(f['path'].lower().endswith(('.dsa','.ds')) for f in snapshot['manifest']): result['notes'].append('DAZ feature tracing remains limited; saved source and dependency views remain available.')
    if not result['outlines']: result['notes'].append('No supported function outline is available within the parsing budget. Read the saved dependencies and source.')
    result['qualification'] = 'Static reading outline; not an observed runtime trace. Python top-level functions and compiler-backed JavaScript/TypeScript declarations only; 24 files, depth two, 30 steps, 12 outlines. Branches are alternatives. Dynamic targets, bindings and network boundaries remain unconfirmed. Test association is not proof of coverage or passing tests.'
    return result


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


GLOSSARY = {
    'responsibility': 'The job a part owns. Keeping related work together makes it easier to find and change.',
    'dependency': 'A part asks another part for something. A saved import shows a dependency, not execution order.',
    'boundary': 'Where one part hands work or data to another through a defined interface.',
    'state': 'Information the program keeps while it works. Its lifetime depends on where and how it is stored.',
    'persistence': 'Keeping information after the program closes. Saving can fail, so recovery matters too.',
    'validation': 'Checking that an input satisfies a rule before relying on it.',
    'testing': 'Checking expected behavior. A saved assertion describes an expectation; it does not prove a test passed.',
    'coupling': 'How much a change in one part requires changes in another.',
    'tradeoff': 'What a choice improves and what it costs or makes harder.',
}


def saved_glossary(settings, snapshot, review):
    concepts = {'responsibility':'responsibilities', 'dependency':'dependencies', 'boundary':'data_flow', 'state':'state', 'persistence':'state', 'validation':'validation', 'testing':'testing', 'coupling':'change_impact', 'tradeoff':'tradeoffs'}
    return [{'term':term, 'meaning':meaning, 'examples':concept_examples(settings,snapshot,review,concepts[term])} for term,meaning in GLOSSARY.items()]
