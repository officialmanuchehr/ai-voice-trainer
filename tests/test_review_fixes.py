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
