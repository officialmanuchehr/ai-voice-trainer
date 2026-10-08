"""Private review regressions; real DB/HTTP/JS with offline stub providers."""
import asyncio
import json
import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from support import PASSWORD, create_scenario, kb_data, login, new_product, ok, scenario_data, server, uid

from app.models import KnowledgeBase, ScenarioVersion
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.parametrize('kind', ['kb', 'scenario'])
@pytest.mark.parametrize('winner', ['edit', 'approve'])
def test_concurrent_edit_and_approval_cannot_both_commit(server, monkeypatch, kind, winner):
    product = new_product(publish=False)
    editor = login('admin')
    approver = login('admin')
    if kind == 'kb':
        url = f'/admin/kb/{product}/versions/1.0.0'
        edit_url = url
        model = KnowledgeBase
    else:
        sid = create_scenario(scenario_data(product))
        url = f'/admin/scenarios/{sid}/versions/1'
        edit_url = f'/admin/scenarios/{sid}'
        model = ScenarioVersion
    before = ok(editor.get(url))
    content = {**before['data'], ('name' if kind == 'kb' else 'title'): 'Новое содержимое'}
    barrier = threading.Barrier(2)
    committed = threading.Event()
    original = AsyncSession.commit

    async def ordered_commit(db):
        changed = next((v for v in db.dirty if isinstance(v, model)), None)
        if changed is None:
            return await original(db)
        operation = 'approve' if changed.status == 'approved' else 'edit'
        # Both requests have read the same revision before either writes.
        await asyncio.to_thread(barrier.wait, 10)
        if operation != winner:
            assert await asyncio.to_thread(committed.wait, 10)
        try:
            return await original(db)
        finally:
            if operation == winner:
                committed.set()

    monkeypatch.setattr(AsyncSession, 'commit', ordered_commit)
    with ThreadPoolExecutor(max_workers=2) as pool:
        edit = pool.submit(editor.put, edit_url, json={'data': content, 'revision': before['revision'], 'base_version': 1})
        approve = pool.submit(approver.post, url + '/status', json={'status': 'approved', 'revision': before['revision']})
        responses = {'edit': edit.result(timeout=20), 'approve': approve.result(timeout=20)}
    assert responses[winner].status_code == 200
    assert responses['approve' if winner == 'edit' else 'edit'].status_code == 409
    after = ok(editor.get(url))
    assert after['revision'] == before['revision'] + 1
    assert after['status'] == ('draft' if winner == 'edit' else 'approved')
    assert after['data'] == (content if winner == 'edit' else before['data'])


@pytest.mark.parametrize('kind', ['kb', 'scenario'])
def test_approval_rejects_revision_changed_since_review(server, kind):
    product = new_product(publish=False)
    admin = login('admin')
    if kind == 'kb':
        url = f'/admin/kb/{product}/versions/1.0.0'
        edit_url = url
    else:
        sid = create_scenario(scenario_data(product))
        url = f'/admin/scenarios/{sid}/versions/1'
        edit_url = f'/admin/scenarios/{sid}'
    reviewed = ok(admin.get(url))
    ok(admin.put(edit_url, json={'data': reviewed['data'], 'base_version': 1, 'revision': reviewed['revision']}))
    stale = admin.post(url + '/status', json={'status': 'approved', 'revision': reviewed['revision']})
    assert stale.status_code == 409
    current = ok(admin.get(url))
    assert current['status'] == 'draft'
    ok(admin.post(url + '/status', json={'status': 'approved', 'revision': current['revision']}))


def test_password_reset_revokes_all_old_cookies_and_allows_new_login(server):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.security import _sign, COOKIE_NAME
    import time

    admin = login('admin')
    username = uid('reset')
    user = ok(admin.post('/admin/users', json={'username': username, 'full_name': username, 'role': 'manager', 'password': PASSWORD}))
    old = [login(username), login(username)]
    # Old three-part cookies survive migration only until the first reset.
    payload = f"{user['id']}.{int(time.time()) + 3600}"
    legacy = TestClient(app, cookies={COOKIE_NAME: f'{payload}.{_sign(payload)}'})
    assert legacy.get('/auth/me').status_code == 200
    new_password = 'replacement-test-password'
    ok(admin.put(f"/admin/users/{user['id']}", json={'full_name': username, 'role': 'manager', 'password': new_password}))
    for client in [*old, legacy]:
        assert client.get('/auth/me').status_code == 401
        assert client.get('/scenarios').status_code == 401
    assert TestClient(app).post('/auth/login', json={'username': username, 'password': PASSWORD}).status_code == 401
    fresh = login(username, new_password)
    assert fresh.get('/auth/me').status_code == 200
    ok(admin.put(f"/admin/users/{user['id']}", json={'full_name': username, 'role': 'manager', 'password': new_password}))
    assert fresh.get('/auth/me').status_code == 401


def test_additive_migration_backfills_revisions_and_is_idempotent():
    from sqlalchemy import create_engine, text, inspect
    from app.database import Base
    from app.main import _add_missing_columns

    engine = create_engine('sqlite://')
    with engine.begin() as conn:
        Base.metadata.create_all(conn)
        for table, column in [('users', 'session_revision'), ('knowledge_base', 'revision'), ('scenario_versions', 'revision')]:
            conn.execute(text(f'ALTER TABLE {table} DROP COLUMN {column}'))
        conn.execute(text("INSERT INTO users (id, username, full_name, password_hash, role, is_active, created_at) VALUES ('u', 'u', 'U', 'hash', 'manager', 1, CURRENT_TIMESTAMP)"))
        conn.execute(text("INSERT INTO knowledge_base (product_id, version, data, status, created_at) VALUES ('p', '1', '{}', 'draft', CURRENT_TIMESTAMP)"))
        conn.execute(text("INSERT INTO scenario_versions (scenario_id, version, data, status, created_at) VALUES ('s', 1, '{}', 'draft', CURRENT_TIMESTAMP)"))
        _add_missing_columns(conn)
        _add_missing_columns(conn)
        for table, column, default in [('users', 'session_revision', 0), ('knowledge_base', 'revision', 1), ('scenario_versions', 'revision', 1)]:
            assert conn.scalar(text(f'SELECT {column} FROM {table}')) == default
            assert next(c for c in inspect(conn).get_columns(table) if c['name'] == column)['nullable'] is False
    engine.dispose()


NODE = shutil.which('node')


@pytest.mark.parametrize('kind', ['kb', 'scenario'])
def test_concurrent_first_publications_keep_one_current_version(server, monkeypatch, kind):
    from sqlalchemy.sql.dml import Update

    product = new_product(publish=kind == 'scenario')
    admin = login('admin')
    if kind == 'kb':
        root = f'/admin/kb/{product}/versions'
        versions = ['1.0.0', '2.0.0']
        ok(admin.post(root, json={'version': versions[1], 'base_version': versions[0]}))
        parent_table, version_table = 'products', 'knowledge_base'
    else:
        data = scenario_data(product)
        sid = create_scenario(data)
        root = f'/admin/scenarios/{sid}/versions'
        versions = [1, 2]
        ok(admin.post(f'{root}/1/status', json={'status': 'approved'}))
        ok(admin.put(f'/admin/scenarios/{sid}', json={'data': {**data, 'title': 'Second version'}, 'base_version': 1}))
        parent_table, version_table = 'scenarios', 'scenario_versions'
    for version in versions:
        if kind == 'scenario' and version == 1:
            continue
        ok(admin.post(f'{root}/{version}/status', json={'status': 'approved'}))

    barrier = threading.Barrier(2)
    original = AsyncSession.execute

    async def concurrent_execute(db, statement, *args, **kwargs):
        if isinstance(statement, Update) and statement.table.name == parent_table:
            await asyncio.to_thread(barrier.wait, 30)
            result = await original(db, statement, *args, **kwargs)
            db.info['publication_parent_locked'] = True
            return result
        compiled = statement.compile()
        # Without the shared parent lock, force both requests to observe the
        # empty publication set, making the old defect deterministic.
        if (not db.info.get('publication_parent_locked')
                and version_table in str(statement)
                and 'published' in compiled.params.values()):
            result = await original(db, statement, *args, **kwargs)
            await asyncio.to_thread(barrier.wait, 30)
            return result
        return await original(db, statement, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, 'execute', concurrent_execute)
    clients = [login('admin'), login('admin')]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(client.post, f'{root}/{version}/status', json={'status': 'published'})
                   for client, version in zip(clients, versions)]
        assert [f.result(timeout=60).status_code for f in futures] == [200, 200]
    current = [ok(admin.get(f'{root}/{version}')) for version in versions]
    assert sorted(v['status'] for v in current) == ['archived', 'published']
    if kind == 'scenario':
        from app.database import SessionLocal
        from app.models import Scenario
        async def published_pointer():
            async with SessionLocal() as db:
                return (await db.get(Scenario, sid)).published_version
        published = next(version for version, v in zip(versions, current) if v['status'] == 'published')
        assert asyncio.run(published_pointer()) == published


@pytest.mark.skipif(NODE is None, reason='Node required to execute the real login page')
@pytest.mark.parametrize('next_path,expected', [
    ('/history?view=all', 'https://trainer.example/history?view=all'),
    ('/\\attacker.example', '/overview'),
    ('//attacker.example', '/overview'),
    ('https://attacker.example/', '/overview'),
    ('javascript:alert(1)', '/overview'),
    ('http://[', '/overview'),
    ('', '/overview'),
])
def test_login_return_address_stays_on_current_origin(next_path, expected):
    path = Path(__file__).resolve().parents[1] / 'static/js/pages/login.js'
    script = r'''
const fs=require('fs'), vm=require('vm'), assert=require('assert');
let submit;
const el={value:'test',append(){},classList:{add(){},remove(){}},addEventListener(_,fn){submit=fn;}};
const ctx={URL,URLSearchParams,document:{getElementById(){return el;}},themeSelect(){return {};},setLoading(){},
 api:async()=>({role:'manager'}),location:{origin:'https://trainer.example',search:'?next='+encodeURIComponent(NEXT)}};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(PATH,'utf8'),ctx);
(async()=>{await submit({preventDefault(){}});assert.strictEqual(ctx.location.href,EXPECTED);})().catch(e=>{console.error(e);process.exit(1);});
'''
    script = 'const NEXT=' + json.dumps(next_path) + ', EXPECTED=' + json.dumps(expected) + ', PATH=' + json.dumps(str(path)) + ';\n' + script
    subprocess.run([NODE, '-e', script], check=True, capture_output=True, text=True, timeout=15)


@pytest.mark.skipif(NODE is None, reason='Node required to execute the real training page')
@pytest.mark.parametrize('status,finish_calls,poll_calls', [('finished', 0, 0), ('scoring', 0, 1), ('active', 1, 1), ('finish_error', 1, 1), ('unknown', 0, 0), ('network_error', 0, 0)])
def test_scoring_retry_executes_real_page(status, finish_calls, poll_calls):
    path = Path(__file__).resolve().parents[1] / 'static/js/pages/training.js'
    script = r'''
const vm = require('vm'), fs = require('fs'), assert = require('assert');
const elements = new Map();
const element = (id) => {
  if (!elements.has(id)) elements.set(id, {dataset:{}, classList:{add(){},remove(){}}, querySelector(){return element(id+'child');}, scrollIntoView(){}, focus(){}, addEventListener(){}});
  return elements.get(id);
};
let finish = 0, runs = 0, renders = 0;
const result = {status:'finished', total:81};
const ctx = {
 document:{getElementById:element, addEventListener(){}},
 api: async (url) => {
   if (url.endsWith('/finish')) {finish++; return {status:'scoring'};}
   if (STATUS === 'network_error') throw new Error('network');
   return STATUS === 'finished' ? result : {status:STATUS};
 },
 fetch:async () => {runs++;},
 renderResult: async (_, data) => {assert.strictEqual(data,result); renders++; if (STATUS === 'finished' && renders === 1) throw new Error('rubric network');},
 clearInterval(){}, navigator:{}, window:{},
};
vm.createContext(ctx);
let source = fs.readFileSync(PATH, 'utf8');
// Do not start catalogue bootstrap; execute the actual finish function and UI.
source = source.slice(0, source.indexOf("$('product-filter').addEventListener"));
vm.runInContext(source + '\nsessionId="saved"; pollScore = async () => {polls++; return result;};', ctx);
// polls/result are provided in-context, with the same object identity.
ctx.polls = 0; ctx.result = result;
(async () => {
 await ctx.finishSession();
 if (STATUS === 'finished') await ctx.finishSession(); // recover from failed result rendering
 assert.strictEqual(finish, FINISH);
 assert.strictEqual(ctx.polls, POLLS);
 assert.strictEqual(runs, POLLS);
 if (['unknown','network_error'].includes(STATUS)) assert.strictEqual(renders,0);
 else assert.strictEqual(renders, STATUS === 'finished' ? 2 : 1);
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
    script = 'const STATUS=' + json.dumps(status) + ', PATH=' + json.dumps(str(path)) + f', FINISH={finish_calls}, POLLS={poll_calls};\n' + script
    result = subprocess.run([NODE, '-e', script], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
