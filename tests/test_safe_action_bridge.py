"""Offline authenticated API and atomic durable-decision tests."""
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import subprocess

import pytest
from starlette.testclient import TestClient

from arqon_os.api import create_app
from arqon_os.safe_action import PersistentSafeActionWorkflow, ProposalConflictError, SafeActionError
from arqon_os.tools.approvals import ApprovalManager, ActorKind


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*args, **kwargs):
        pytest.fail('Unexpected network access')
    monkeypatch.setattr(socket.socket, 'connect', deny)
    monkeypatch.setattr(socket, 'getaddrinfo', deny)


class Peer:
    def __init__(self, app, peer='127.0.0.1'):
        self.app, self.peer = app, peer
    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http':
            scope = dict(scope, client=(self.peer, 12345))
        await self.app(scope, receive, send)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    path = tmp_path/'shared.db'
    key = secrets.token_urlsafe(32)
    monkeypatch.setenv('ARQON_OPERATOR_KEY', key)
    flow = PersistentSafeActionWorkflow(path, ApprovalManager(frozenset({'local-operator'})))
    flow.initialize()
    proposal = flow.prepare()
    with TestClient(Peer(create_app(path)), base_url='http://127.0.0.1') as client:
        yield path, flow, proposal, client, {'Authorization': 'Bearer ' + key}


def url(proposal, action=''):
    return '/api/v1/operator/proposals/' + proposal.proposal_id + action


def review(client, proposal, headers):
    response = client.get(url(proposal), headers=headers)
    assert response.status_code == 200
    return response.json()['fingerprint']


@pytest.mark.parametrize('auth', [None, 'Bearer invalid', 'Bearer approved=true'])
def test_authentication(setup, auth):
    path, flow, proposal, client, headers = setup
    supplied = {} if auth is None else {'Authorization': auth}
    assert client.get(url(proposal), headers=supplied).status_code == 401
    for action in ('/approve', '/reject'):
        assert client.post(url(proposal, action), headers=supplied, json={}).status_code == 401
    assert flow.get(proposal.proposal_id) is None


def test_unconfigured_and_locality(setup, monkeypatch):
    path, flow, proposal, client, headers = setup
    for forwarded in ('x-forwarded-for', 'forwarded', 'x-real-ip'):
        assert client.get(url(proposal), headers=headers | {forwarded: '127.0.0.1'}).status_code == 403
    with TestClient(Peer(create_app(path), '192.0.2.1'), base_url='http://localhost') as remote:
        assert remote.get(url(proposal), headers=headers).status_code == 403
    monkeypatch.delenv('ARQON_OPERATOR_KEY')
    with TestClient(Peer(create_app(path)), base_url='http://localhost') as unconfigured:
        assert unconfigured.get(url(proposal), headers=headers).status_code == 503


@pytest.mark.parametrize('action,status', [('approve','approved'), ('reject','rejected')])
def test_decision_and_replay(setup, action, status):
    path, flow, proposal, client, headers = setup
    fingerprint = review(client, proposal, headers)
    response = client.post(url(proposal, '/' + action), headers=headers, json={'fingerprint': fingerprint})
    assert response.status_code == 200 and response.json()['status'] == status
    assert (flow.get(proposal.proposal_id) is not None) == (action == 'approve')
    assert flow.get_proposal(proposal.proposal_id).status == status
    assert client.post(url(proposal, '/approve'), headers=headers, json={'fingerprint': fingerprint}).status_code == 409
    assert client.post(url(proposal, '/reject'), headers=headers, json={'fingerprint': fingerprint}).status_code == 409
    with sqlite3.connect(path) as conn:
        assert conn.execute('SELECT count(*) FROM safeaction_checklists').fetchone()[0] == (action == 'approve')


def test_tampered_and_review_binding(setup):
    path, flow, proposal, client, headers = setup
    fingerprint = review(client, proposal, headers)
    assert client.post(url(proposal, '/approve'), headers=headers, json={'fingerprint': '0'*64}).status_code == 409
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE safeaction_proposals SET title='tampered' WHERE proposal_id=?", (proposal.proposal_id,))
    assert client.get(url(proposal), headers=headers).status_code == 409
    assert client.post(url(proposal, '/approve'), headers=headers, json={'fingerprint': fingerprint}).status_code == 409
    assert flow.get(proposal.proposal_id) is None


def test_expired(setup):
    path, flow, proposal, client, headers = setup
    fingerprint = review(client, proposal, headers)
    now = datetime.now(UTC)
    with sqlite3.connect(path) as conn:
        conn.execute('UPDATE safeaction_proposals SET created_at=?,expires_at=? WHERE proposal_id=?',
            ((now-timedelta(minutes=11)).isoformat(), (now-timedelta(minutes=1)).isoformat(), proposal.proposal_id))
    assert client.post(url(proposal, '/approve'), headers=headers, json={'fingerprint': fingerprint}).status_code == 409
    with sqlite3.connect(path) as conn:
        assert conn.execute('SELECT status FROM safeaction_proposals').fetchone()[0] == 'expired'
    assert flow.get(proposal.proposal_id) is None


@pytest.mark.parametrize('body', [{'approved':True}, {'fingerprint':'0'*64,'role':'operator'}, {'fingerprint':1}])
def test_strict_operator_body(setup, body):
    _, _, proposal, client, headers = setup
    assert client.post(url(proposal, '/approve'), headers=headers, json=body).status_code == 400


def test_concurrent_approval(setup):
    path, flow, proposal, client, headers = setup
    fingerprint = review(client, proposal, headers)
    def decide(_):
        other = PersistentSafeActionWorkflow(path, ApprovalManager(frozenset({'local-operator'})))
        other.initialize()
        try:
            return other.decide_proposal(proposal.proposal_id, fingerprint=fingerprint, approve=True,
                decided_by='local-operator', actor_kind=ActorKind.HUMAN, human_confirmed=True,
                grants=frozenset({'checklist.save'})).status
        except ProposalConflictError:
            return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(decide, range(2))) == ['approved','conflict']
    with sqlite3.connect(path) as conn:
        assert conn.execute('SELECT count(*) FROM safeaction_checklists').fetchone()[0] == 1


def test_write_failure_rolls_back_decision_and_save(setup):
    path, flow, proposal, client, headers = setup
    fingerprint = review(client, proposal, headers)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TRIGGER deny_decision BEFORE UPDATE ON safeaction_proposals BEGIN SELECT RAISE(ABORT,'private detail'); END")
    response = client.post(url(proposal, '/approve'), headers=headers, json={'fingerprint': fingerprint})
    assert response.status_code == 500 and 'private' not in response.text
    with sqlite3.connect(path) as conn:
        assert conn.execute('SELECT status FROM safeaction_proposals').fetchone()[0] == 'pending'
        assert conn.execute('SELECT count(*) FROM safeaction_checklists').fetchone()[0] == 0


def test_separate_mcp_process_to_api(setup):
    path, flow, proposal, client, headers = setup
    root = Path(__file__).resolve().parents[1]
    script = '''
import asyncio, sys, json
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
async def main():
    params = StdioServerParameters(command=sys.executable, args=['-B','-m','arqon_os.mcp_server','--database',sys.argv[1]])
    async with stdio_client(params) as (read,write):
        async with ClientSession(read,write) as client:
            await client.initialize()
            result = await client.call_tool('arqon_propose_checklist', {'workflow':'travel'})
            assert not result.isError
            for name in ('arqon_approve_checklist','arqon_reject_checklist','arqon_save_checklist'):
                assert (await client.call_tool(name, {})).isError
            print(json.dumps(result.structuredContent))
asyncio.run(main())
'''
    result = subprocess.run([os.environ.get('ARQON_MCP_PYTHON', str(root/'.venv-mcp/bin/python')), '-B', '-c', script, str(path)],
                            cwd=root, capture_output=True, text=True, timeout=30, check=True)
    data = json.loads(result.stdout)
    response = client.get('/api/v1/operator/proposals/' + data['proposal_id'], headers=headers)
    assert response.status_code == 200 and response.json()['status'] == 'pending'
    assert response.json()['title'] == data['title'] and response.json()['items'] == data['items']
