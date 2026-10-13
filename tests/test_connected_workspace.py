from fastapi.testclient import TestClient

from archcoach.app import create_app
from tests.fixtures.learning_profile import seed_profile


def workspace(tmp_path, monkeypatch):
    settings, ids = seed_profile(tmp_path)
    class NoInference:
        def status(self):
            raise AssertionError('Saved reading must not probe providers')
        def run_structured(self, *args, **kwargs):
            raise AssertionError('Opening saved reading must not run inference')
    monkeypatch.setattr('archcoach.app.create_adapter', lambda _: NoInference())
    app = create_app(settings, start_worker=False)
    return app, TestClient(app), ids


def test_full_workspace_navigation_and_instructor_follow_saved_review(tmp_path, monkeypatch):
    app, client, ids = workspace(tmp_path, monkeypatch)
    before = app.state.store.get_review(ids['before'])
    for suffix in ('', '/map', '/walkthrough', '/session', '/glossary', '/source?path=service.py&line=3&end_line=4'):
        response = client.get(f"/reviews/{ids['before']}{suffix}")
        assert response.status_code == 200
        assert 'Saved review learning' in response.text
        assert 'Ask instructor' in response.text and 'Architecture instructor' in response.text
        assert f'/reviews/{ids["before"]}#quiz' in response.text
        assert before['created_at'][:10] in response.text
        assert 'Codex' in response.text
        assert 'New instructor answers use' in response.text
    main = client.get(f'/reviews/{ids["before"]}').text
    assert 'id="learning-map"' in main and '/walkthrough-map?role=runtime' in main
    assert main.count('Citations identify saved text;') == 1
    assert client.get('/reviews/unknown/map').status_code == 404
    assert app.state.store.get_review(ids['before']) == before
    with app.state.store.connect() as conn:
        assert conn.execute('SELECT count(*) FROM jobs').fetchone()[0] == 0


def test_missing_diagram_and_legacy_quiz_have_actionable_states(tmp_path, monkeypatch):
    app, client, ids = workspace(tmp_path, monkeypatch)
    with app.state.store.connect() as conn:
        conn.execute('UPDATE reviews SET critique_json=? WHERE id=?', ('{"lessons":[],"quiz":[],"findings":[],"strengths":[]}', ids['before']))
    assert 'Original rendered diagram unavailable' in client.get(f'/reviews/{ids["before"]}/map').text
    text = client.get(f'/reviews/{ids["before"]}').text
    assert 'No questions were saved' in text and 'new review deliberately' in text


def test_saved_graph_counts_internal_imports_and_bounds_views():
    from archcoach.workspace import saved_graph, source_role
    paths = [f'pkg/part{i:02}.py' for i in range(45)]
    snapshot = {'manifest': [{'path': p, 'lines': 2} for p in paths], 'analysis': {
        'edges': [{'source': paths[0], 'target': p, 'line': 1} for p in paths[1:]],
        'unresolved_imports': []}}
    review = {'architecture': {'components': [{'id': 'pkg', 'source_paths': paths}]}}
    graph = saved_graph(snapshot, review, component='pkg')
    assert len(graph['nodes']) == 40 and graph['omitted_nodes'] == 5
    assert graph['omitted_edges'] == 5
    assert graph['nodes'][0]['outgoing'] == snapshot['analysis']['edges']
    assert graph['internal_count'] == 44
    assert len(saved_graph(snapshot, review, query='part44')['nodes']) == 1
    assert source_role('README.md') == 'supporting'
    assert source_role('tests/example.ts') == 'tests'
    assert source_role('tools/build.py') == 'tooling'
    assert source_role('src/db.py') == 'runtime'


def test_context_selection_is_validated_before_queueing(tmp_path, monkeypatch):
    app, client, ids = workspace(tmp_path, monkeypatch)
    headers = {'X-ArchCoach-Token': app.state.csrf_token}
    route = f'/api/reviews/{ids["before"]}/chat'
    for selection in ({'kind':'component','id':'foreign'}, {'kind':'source','path':'../secret','line':1}, {'kind':'source','path':'service.py','line':99}, {'kind':'relationship','id':'-1'}):
        assert client.post(route, json={'message':'Explain', 'selection':selection}, headers=headers).status_code == 422
    selection = {'kind':'source','path':'service.py','line':3,'end_line':4}
    response = client.post(route, json={'message':'Explain', 'selection':selection}, headers=headers)
    assert response.status_code == 202
    assert app.state.store.get_job(response.json()['job_id'])['payload']['selection']['path'] == 'service.py'


def test_graph_api_uses_saved_analysis_when_current_folder_changes(tmp_path, monkeypatch):
    app, client, ids = workspace(tmp_path, monkeypatch)
    with app.state.store.connect() as conn:
        conn.execute('UPDATE snapshots SET analysis_json=? WHERE id=?', ('{"edges":[{"source":"main.py","target":"service.py","line":1}]}', app.state.store.get_review(ids['before'])['snapshot_id']))
    graph = client.get(f'/api/reviews/{ids["before"]}/graph').json()
    assert graph['known'] and len(graph['edges']) == 1
    assert client.get(f'/api/reviews/{ids["before"]}/graph?component=foreign').status_code == 422
    assert client.get(f'/api/reviews/{ids["before"]}/graph?focus=../secret').status_code == 422


def test_typescript_reading_follows_saved_arrow_function_and_alternative_branch(tmp_path):
    import hashlib
    from archcoach.learning import source_walkthroughs
    from archcoach.db import Store
    settings, ids = seed_profile(tmp_path)
    store = Store(settings.db_path); review = store.get_review(ids['before'])
    snapshot = store.get_snapshot(review['snapshot_id'])
    files = {'web/tsconfig.json':'{"compilerOptions":{"baseUrl":".","paths":{"@/*":["*"]}}}',
             'web/service.ts':'export const format = (name: string) => {\n if (!name) { throw new Error("empty"); }\n return "Hello " + name;\n};\n',
             'web/main.ts':'import {format} from "@/service";\nexport function run(name: string) {\n return format(name);\n}\n'}
    for path, text in files.items():
        digest = hashlib.sha256(text.encode()).hexdigest()
        blob = settings.blob_dir/digest[:2]/digest; blob.parent.mkdir(exist_ok=True); blob.write_text(text,encoding='utf-8')
        snapshot['manifest'].append({'path':path,'sha256':digest,'lines':len(text.splitlines())})
    outlines = source_walkthroughs(settings,snapshot,review)
    run = next(o for o in outlines['outlines'] if o['name']=='web/main.ts · run')
    assert any(s['example']['path']=='web/service.ts' for s in run['steps'])
    assert any('is true' in s['explanation'] and 'throws' in s['explanation'] for s in run['steps'])
    assert 'observed runtime trace' in outlines['qualification']
    assert store.get_snapshot(review['snapshot_id'])['manifest'] != snapshot['manifest']


def test_python_reading_excludes_statements_after_unconditional_raise(tmp_path):
    import hashlib
    from archcoach.learning import source_walkthroughs
    from archcoach.db import Store
    settings, ids = seed_profile(tmp_path)
    store = Store(settings.db_path); review = store.get_review(ids['before']); snapshot=store.get_snapshot(review['snapshot_id'])
    text='def stop():\n    raise ValueError("stop")\n    should_not_be_a_step()\n'
    digest=hashlib.sha256(text.encode()).hexdigest(); blob=settings.blob_dir/digest[:2]/digest;blob.parent.mkdir(exist_ok=True);blob.write_text(text)
    snapshot['manifest']=[{'path':'stop.py','sha256':digest,'lines':3}]
    steps=source_walkthroughs(settings,snapshot,review)['outlines'][0]['steps']
    assert not any('should_not_be_a_step' in s['explanation'] for s in steps)


def test_session_sparse_updates_and_reopen_keep_saved_context(tmp_path, monkeypatch):
    app, client, ids = workspace(tmp_path, monkeypatch)
    headers = {'X-ArchCoach-Token':app.state.csrf_token}
    url=f'/api/reviews/{ids["before"]}/session'
    selected={'kind':'source','path':'service.py','line':3,'end_line':4}
    assert client.patch(url,headers=headers,json={'position':2,'draft':'Why does this check run here?','selection':selected}).status_code == 200
    client.patch(url,headers=headers,json={'next_step':'Inspect the store boundary.'})
    state=client.get(url).json()
    assert state['draft']=='Why does this check run here?' and state['selection']==selected
    assert client.patch(url,headers=headers,json={'selection':{**selected,'line':99}}).status_code==422
    assert client.get(url).json()==state
    reopened=create_app(app.state.settings,start_worker=False)
    assert reopened.state.store.learning_session(ids['before'])==state
    assert reopened.state.store.learning_session(ids['after'])=={}
    assert 'Why does this check run here?' in client.get(f'/reviews/{ids["before"]}/session').text


def test_uncertainty_first_attempt_retry_and_flag_preserve_history(tmp_path, monkeypatch):
    app, client, ids=workspace(tmp_path,monkeypatch)
    headers={'X-ArchCoach-Token':app.state.csrf_token}; rid=ids['before']; question='fact-1'
    original=app.state.store.get_review(rid)['critique']
    url=f'/reviews/{rid}/quiz/{question}'
    payload={'outcome':'not_sure','request_id':'uncertain-first'}
    first=client.post(url,headers=headers,json=payload)
    assert first.status_code==200 and first.json()['selected_index'] is None and not first.json()['correct']
    assert client.post(url,headers=headers,json=payload).json()['attempt_id']==first.json()['attempt_id']
    assert client.post(url,headers=headers,json={'selected_index':0,'outcome':'not_sure'}).status_code==422
    assert client.post(url,headers=headers,json={'selected_index':0,'request_id':'correct-retry'}).json()['correct']
    attempts=app.state.store.quiz_attempts(rid,question)
    assert [a['kind'] for a in attempts]==['first','retry'] and attempts[0]['outcome']=='not_sure'
    flag=client.post(f'/api/reviews/{rid}/issues',headers=headers,json={'kind':'quiz','target_id':question,'note':'The explanation seems incomplete.'}).json()['id']
    assert client.post(url,headers=headers,json={'selected_index':0}).status_code==409
    assert 'Mark reviewed and resolve' in client.get(f'/reviews/{rid}').text
    assert not any(r['question_id']==question for r in app.state.store.learning_records())
    assert client.post(f'/api/reviews/{ids["after"]}/issues/{flag}/resolve',headers=headers).status_code==404
    assert client.post(f'/api/reviews/{rid}/issues/{flag}/resolve',headers=headers).status_code==200
    assert any(r['question_id']==question and r['first_outcome']=='not_sure' for r in app.state.store.learning_records())
    assert app.state.store.get_review(rid)['critique']==original
    assert len(app.state.store.quiz_attempts(rid,question))==2


def test_version_nine_migration_preserves_notes_attempts_and_snapshot(tmp_path, monkeypatch):
    from archcoach.db import Store
    app, _, ids=workspace(tmp_path,monkeypatch); store=app.state.store; rid=ids['before']
    original=store.get_review(rid); store.save_learning_note(rid,'fact-0','A private correction')
    store.set_lesson_status(rid,'boundary','learning')
    conversation=store.conversation_for_review(rid); store.add_message(conversation['id'],'assistant','Saved explanation',[])
    with store.connect() as conn:
        conn.execute('DROP TABLE learning_sessions');conn.execute('DROP TABLE learning_issues')
        conn.execute('ALTER TABLE quiz_answers DROP COLUMN outcome');conn.execute('ALTER TABLE quiz_attempts DROP COLUMN outcome')
        conn.execute('PRAGMA user_version=9')
    upgraded=Store(store.path)
    assert upgraded.get_review(rid)==original
    assert upgraded.quiz_attempts(rid)[0]['outcome']=='answered'
    assert upgraded.learning_records()[0]['note']=='A private correction'
    assert upgraded.lesson_statuses(rid)['boundary']=='learning'
    assert upgraded.conversation_for_review(rid)['messages'][0]['content']=='Saved explanation'
    assert list((store.path.parent/'backups').glob('*-v9-*.db'))


def test_tiny_quiz_is_grounded_and_allows_no_questions():
    from archcoach.review import heuristic_quiz,heuristic_architecture,validate_critique_quality
    from archcoach.models import Critique
    analysis={'files':[{'path':'only.py','lines':2,'language':'python','definitions':[{'name':'greet','kind':'function','line':1}]}],'edges':[],'cycles':[]}
    architecture=heuristic_architecture({'name':'Tiny'},analysis)
    quiz=heuristic_quiz(analysis,architecture)
    assert len(quiz)==1 and quiz[0].evidence[0].path=='only.py'
    assert architecture.components[0].kind=='unknown' and not architecture.main_path
    assert validate_critique_quality(Critique(quiz=[])).quiz==[]
    analysis['files'][0]['definitions']=[]
    assert heuristic_quiz(analysis,architecture)==[]


def test_file_size_alone_does_not_create_placeholder_teaching():
    from archcoach.review import heuristic_architecture, heuristic_critique
    analysis={'files':[{'path':'large.py','lines':600,'language':'python','definitions':[]}],'edges':[],'cycles':[]}
    architecture=heuristic_architecture({'name':'Large'},analysis)
    critique=heuristic_critique(analysis,architecture)
    assert critique.lessons==[] and critique.quiz==[]
    assert critique.findings[0].observation=='large.py has 600 lines.'


def test_missing_entry_guard_and_invalid_graph_evidence_are_not_confirmed(tmp_path,monkeypatch):
    app,client,ids=workspace(tmp_path,monkeypatch);store=app.state.store
    assert client.get(f'/reviews/{ids["before"]}/source?path=service.py&line=999').status_code==422
    walkthrough=client.get(f'/api/reviews/{ids["before"]}/walkthrough').json()
    main=next(o for o in walkthrough['outlines'] if o['name']=='main.py · main')
    assert 'unconfirmed' in main['entry'] and 'command' not in main['entry']
    snapshot=store.get_snapshot(store.get_review(ids['before'])['snapshot_id'])
    snapshot['analysis']['edges']=[{'source':'main.py','target':'service.py','line':999}]
    from archcoach.workspace import saved_graph
    graph=saved_graph(snapshot,store.get_review(ids['before']),role='all')
    assert graph['invalid_edges']==1 and not graph['edges']


def test_detectable_teaching_contradictions_and_quotes(tmp_path,monkeypatch):
    import pytest
    from archcoach.learning import check_teaching_claims
    from archcoach.models import ChatResponse
    app,_,ids=workspace(tmp_path,monkeypatch);store=app.state.store
    snapshot=store.get_snapshot(store.get_review(ids['before'])['snapshot_id'])
    for answer,path in [('All tests passed.','service.py'),('main is the CLI entry point.','main.py'),('The empty check rejects whitespace-only names.','service.py'),('Saved code:\n```python\ndef handle(name):\n    save(name)\n```','service.py')]:
        with pytest.raises(ValueError): check_teaching_claims(app.state.settings,snapshot,ChatResponse(answer=answer,citations=[{'path':path,'line':1}]))
    check_teaching_claims(app.state.settings,snapshot,ChatResponse(answer='Hypothetical alternative, assuming validation stays in the caller:\n```python\nstore(name)\n```',citations=[{'path':'service.py','line':1}]))


def test_selected_file_is_prioritized_outside_default_outline_budget(tmp_path):
    import hashlib
    from archcoach.learning import source_walkthroughs
    from archcoach.db import Store
    settings,ids=seed_profile(tmp_path);store=Store(settings.db_path)
    review=store.get_review(ids['before']);snapshot=store.get_snapshot(review['snapshot_id'])
    manifest=[]
    for i in range(28):
        text=f'def item_{i}():\n    return {i}\n';digest=hashlib.sha256(text.encode()).hexdigest()
        blob=settings.blob_dir/digest[:2]/digest;blob.parent.mkdir(exist_ok=True);blob.write_text(text)
        manifest.append({'path':f'module{i:02}.py','sha256':digest,'lines':2})
    snapshot['manifest']=manifest
    selected=source_walkthroughs(settings,snapshot,review,'module27.py')
    assert selected['outlines'][0]['name']=='module27.py · item_27'
    assert len(selected['outlines'])<=12 and any('24-file' in n for n in selected['notes'])


def test_selected_source_survives_a_crowded_packet_budget(tmp_path):
    import hashlib
    from dataclasses import replace
    from archcoach.context import build_source_packets
    settings,_=seed_profile(tmp_path)
    manifest=[]
    for path,text in [('package.json','{"name":"fixture"}\n'*2000),('zz_selected.py','selected_boundary = True\n')]:
        digest=hashlib.sha256(text.encode()).hexdigest();blob=settings.blob_dir/digest[:2]/digest;blob.parent.mkdir(exist_ok=True);blob.write_text(text)
        manifest.append({'path':path,'sha256':digest,'lines':len(text.splitlines())})
    packet,note=build_source_packets(replace(settings,source_packet_chars=8000,source_packet_limit=1),manifest,{},preferred_paths={'zz_selected.py'})
    assert 'selected_boundary = True' in packet and 'zz_selected.py' in packet
    assert 'omitted' in note.lower()


def test_jsx_handler_and_destructured_call_bindings_remain_honest(tmp_path):
    import hashlib
    from archcoach.analyze import _typescript_analysis
    from archcoach.config import Settings
    settings=Settings.load(tmp_path/'private');settings.ensure_dirs()
    texts={'view.tsx': 'function handle() { return "ok"; }\nexport function View() { return <button onClick={handle}>Save</button>; }\n',
           'shadow.tsx': 'function handle() { return "ok"; }\nexport function View({handle}: any) { return <button onClick={handle}>Save</button>; }\n',
           'calls.ts': 'export function handle() { return 1; }\nexport function ambiguous({handle}: any) { return handle(); }\n'}
    manifest=[]
    for path,text in texts.items():
        digest=hashlib.sha256(text.encode()).hexdigest();blob=settings.blob_dir/digest[:2]/digest;blob.parent.mkdir(exist_ok=True);blob.write_text(text)
        manifest.append({'path':path,'sha256':digest,'lines':text.count('\n')})
    by_path,issue=_typescript_analysis(settings,manifest,lambda:False)
    assert issue is None
    assert by_path['view.tsx']['outlines'][0]['entry']=='Direct JSX handler binding'
    assert by_path['shadow.tsx']['outlines'][0]['entry']=='Declared function'
    ambiguous=next(o for o in by_path['calls.ts']['outlines'] if o['name']=='ambiguous')
    assert next(step for step in ambiguous['steps'] if step['title']=='Call')['target'] is None


def test_nested_call_reading_precedes_assignment_in_both_languages(tmp_path):
    import hashlib
    from archcoach.learning import source_walkthroughs
    from archcoach.db import Store
    settings,ids=seed_profile(tmp_path);store=Store(settings.db_path)
    review=store.get_review(ids['before']);snapshot=store.get_snapshot(review['snapshot_id'])
    texts={'order.py':'def clean():\n    return "Ada"\ndef save(name):\n    return name\ndef run(name=clean()):\n    value = save(clean())\n    return value\n',
           'order.ts':'export const clean = () => "Ada";\nexport const save = (name: string) => name;\nexport function run() { return save(clean()); }\n'}
    snapshot['manifest']=[]
    for path,text in texts.items():
        digest=hashlib.sha256(text.encode()).hexdigest();blob=settings.blob_dir/digest[:2]/digest;blob.parent.mkdir(exist_ok=True);blob.write_text(text)
        snapshot['manifest'].append({'path':path,'sha256':digest,'lines':len(text.splitlines())})
    for path in texts:
        result=source_walkthroughs(settings,snapshot,review,path)
        outline=next(o for o in result['outlines'] if o['name']==path+' · run')
        calls=[step['explanation'] for step in outline['steps'] if step['title'] in {'Call','Call site'}]
        assert len(calls)==2 and 'clean' in calls[0] and 'save' in calls[1]
        if path.endswith('.py'):
            state=next(i for i,s in enumerate(outline['steps']) if s['title']=='State or local value')
            assert state>next(i for i,s in enumerate(outline['steps']) if s['title']=='Call site' and 'save' in s['explanation'])


def test_draft_saves_reuse_selected_outline_and_page_restores_file(tmp_path,monkeypatch):
    app,client,ids=workspace(tmp_path,monkeypatch)
    import archcoach.app as module
    original=module.source_walkthroughs;calls=[]
    def tracked(*args,**kwargs):
        calls.append(args[3] if len(args)>3 else kwargs.get('selected_path'))
        return original(*args,**kwargs)
    monkeypatch.setattr(module,'source_walkthroughs',tracked)
    rid=ids['before'];headers={'X-ArchCoach-Token':app.state.csrf_token}
    outline=client.get(f'/api/reviews/{rid}/walkthrough?file=service.py').json()['outlines'][0]
    url=f'/api/reviews/{rid}/session'
    assert client.patch(url,headers=headers,json={'outline_id':outline['id'],'step':1}).status_code==200
    for draft in ('Why','Why does','Why does this part ask store?'):
        assert client.patch(url,headers=headers,json={'draft':draft}).status_code==200
    response=client.get(f'/reviews/{rid}/walkthrough')
    assert response.status_code==200 and 'value="service.py" selected' in response.text
    assert calls==['service.py']
    assert client.get(f'/reviews/{rid}/walkthrough?file=').status_code==200
    assert calls==['service.py', None]
