"""Bounded learning views over saved evidence; never inspect live project files."""
from pathlib import PurePosixPath

from .models import Evidence


CODE = {'.py', '.js', '.jsx', '.ts', '.tsx', '.mjs', '.cjs', '.dsa', '.ds', '.html', '.css', '.sql'}


def source_role(path):
    parts = PurePosixPath(path.lower()).parts
    name = parts[-1]
    if any(p in {'test', 'tests', '__tests__'} for p in parts) or name.startswith('test_') or '.test.' in name or '.spec.' in name:
        return 'tests'
    if any(p in {'scripts', 'tools'} for p in parts):
        return 'tooling'
    if PurePosixPath(path).suffix.lower() in CODE:
        return 'runtime'
    if PurePosixPath(path).suffix.lower() in {'.md', '.txt', '.json', '.yaml', '.yml', '.toml', '.lock', '.html', '.css'}:
        return 'supporting'
    return 'unknown'


def component_role(component):
    roles = {source_role(p) for p in (component.get('source_paths') or [r['path'] for r in component.get('sources', [])])}
    return next(iter(roles)) if len(roles) == 1 else 'unknown'


def saved_graph(snapshot, review, *, component=None, query='', role='runtime', focus=None):
    if role not in {'all', 'runtime', 'tests', 'tooling', 'supporting', 'unknown'}:
        raise ValueError('Unknown source role')
    manifest = {f['path']: f for f in snapshot['manifest']}
    groups = {c['id']: c for c in review['architecture']['components']}
    if component is not None and component not in groups:
        raise ValueError('Component is not in this review')
    paths = set(manifest)
    if component:
        group = groups[component]
        paths &= set(group.get('source_paths') or [r['path'] for r in group.get('sources', [])])
    analysis = snapshot.get('analysis', {})
    recorded = [e for e in analysis.get('edges', []) if e.get('source') in manifest and e.get('target') in manifest]
    edges = [e for e in recorded if isinstance(e.get('line'), int) and 1 <= e['line'] <= manifest[e['source']]['lines']]
    group_facts = {}
    for identifier, group in groups.items():
        members = set(group.get('source_paths') or [r['path'] for r in group.get('sources', [])])
        group_facts[identifier] = {'internal': sum(e['source'] in members and e['target'] in members for e in edges),
            'depends_on': sum(e['source'] in members and e['target'] not in members for e in edges),
            'used_by': sum(e['source'] not in members and e['target'] in members for e in edges), 'known': 'edges' in analysis}
    if focus:
        if focus not in paths:
            raise ValueError('Selected file is outside this saved component')
        paths &= {focus} | {e['source'] for e in edges if e['target'] == focus} | {e['target'] for e in edges if e['source'] == focus}
    selected = sorted(p for p in paths if query.casefold() in p.casefold() and (role == 'all' or source_role(p) == role))
    visible = selected[:40]
    positions = {path: ((i % 4) * 250 + 20, (i // 4) * 125 + 25) for i, path in enumerate(visible)}
    nodes = []
    for path in visible:
        incoming = [e for e in edges if e['target'] == path]
        outgoing = [e for e in edges if e['source'] == path]
        nodes.append({'path': path, 'label': PurePosixPath(path).name, 'role': source_role(path),
                      'x': positions[path][0], 'y': positions[path][1], 'incoming': incoming, 'outgoing': outgoing})
    scoped = [e for e in edges if e['source'] in selected and e['target'] in selected]
    internal = [e for e in scoped if e['source'] in positions and e['target'] in positions]
    drawn = []
    for edge in internal[:80]:
        x, y = positions[edge['source']]; tx, ty = positions[edge['target']]
        drawn.append({**edge, 'd': f'M {x+210} {y+40} C {x+245} {y+80}, {tx-30} {ty+80}, {tx} {ty+40}'})
    return {'format_version': 1, 'nodes': nodes, 'edges': drawn, 'known': 'edges' in analysis,
            'omitted_nodes': max(0, len(selected)-40), 'omitted_edges': len(scoped)-len(drawn),
            'internal_count': sum(e['source'] in paths and e['target'] in paths for e in edges),
            'width': 1020, 'height': max(150, ((len(nodes)+3)//4)*125+30),
            'component': component, 'query': query, 'role': role, 'focus': focus,
            'coverage': analysis.get('coverage', snapshot.get('coverage', {})), 'invalid_edges': len(recorded)-len(edges), 'group_facts':group_facts,
            'unresolved': analysis.get('unresolved_imports', []), 'groups': list(groups.values())}


def resolve_selection(snapshot, review, selection, walkthrough=None):
    """Reject missing, foreign or invalid references before queuing provider work."""
    if selection is None:
        return {'selection': None, 'label': 'Whole saved review', 'evidence': []}
    data = selection.model_dump(exclude_none=True) if hasattr(selection, 'model_dump') else selection
    kind = data['kind']; identifier = data.get('id'); refs = []
    if kind == 'component':
        item = next((c for c in review['architecture']['components'] if c['id'] == identifier), None)
        if not item: raise ValueError('Component is not in this saved review')
        label = item['name']; refs = item.get('sources', [])
    elif kind == 'relationship':
        try: item = review['architecture']['relationships'][int(identifier)]
        except (ValueError, IndexError, TypeError): raise ValueError('Relationship is not in this saved review')
        if int(identifier) < 0: raise ValueError('Relationship index must be positive')
        label = item.get('label', 'Dependency'); refs = item.get('sources', [])
    elif kind in {'lesson', 'quiz'}:
        collection = 'lessons' if kind == 'lesson' else 'quiz'
        item = next((i for i in review['critique'].get(collection, []) if i['id'] == identifier), None)
        if not item: raise ValueError('Learning item is not in this saved review')
        label = item.get('title', item.get('question')); refs = item.get('evidence', [])
    elif kind == 'source':
        label = data['path']; refs = [{'path': label, 'line': data['line'], 'end_line': data.get('end_line')}]
    elif kind == 'walkthrough':
        if data.get('outline_version') != (walkthrough or {}).get('format_version'):
            raise ValueError('Reading outline changed; select the saved step again. Your draft is preserved.')
        item = next((i for i in (walkthrough or {}).get('outlines', []) if i['id'] == identifier), None)
        step = data.get('step', 0)
        if item is None or step < 0 or step >= len(item['steps']): raise ValueError('Walkthrough step is unavailable')
        example = item['steps'][step]['example']; label = item['steps'][step]['title']
        refs = [{key: example[key] for key in ('path', 'line', 'end_line')}]
    elif kind == 'change':
        label = 'Changes in this saved review'
        if identifier != review['id']: raise ValueError('Change selection belongs to another review')
    else:
        raise ValueError('Unknown selection kind')
    manifest = {f['path']: f for f in snapshot['manifest']}
    verified = []
    for raw in refs:
        ref = Evidence.model_validate(raw)
        entry = manifest.get(ref.path)
        if not ref.valid or entry is None or (ref.end_line or ref.line) > entry['lines']:
            raise ValueError('Selected evidence is unavailable or unverified')
        verified.append(ref.model_dump())
    return {'selection': data, 'label': label, 'evidence': verified}
