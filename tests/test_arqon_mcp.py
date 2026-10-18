"""Offline SDK client/server tests; no custom protocol implementation."""
import json
import os
from pathlib import Path
import select
import socket
import subprocess
import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.memory import create_connected_server_and_client_session
from arqon_os.mcp_server import create_server, LOCAL_GRANTS
from arqon_os.runtime.storage import SQLiteRunStore
from arqon_os.tools.approvals import ApprovalManager
from arqon_os.safe_action import SafeActionWorkflow

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def no_external_execution(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError('Forbidden network/approval execution')
    monkeypatch.setattr(socket, 'create_connection', deny)
    monkeypatch.setattr(socket.socket, 'connect', deny)
    monkeypatch.setattr(socket, 'getaddrinfo', deny)
    monkeypatch.setattr(ApprovalManager, 'decide', deny)
    monkeypatch.setattr(ApprovalManager, 'consume', deny)
    monkeypatch.setattr(SafeActionWorkflow, 'approve', deny)
    monkeypatch.setattr(SafeActionWorkflow, 'save', deny)
    class NoScanners:
        def find_spec(self, name, *args):
            if name.startswith(('architect_vapt', 'arqon_os.capabilities', 'arqon_os.tools.local', 'arqon_os.gateway.nebius')):
                raise AssertionError('Forbidden tool/provider import')
    guard = NoScanners()
    sys.meta_path.insert(0, guard)
    yield
    sys.meta_path.remove(guard)


@pytest.mark.asyncio
async def test_discovery_health_mock_and_persistence(tmp_path):
    path = tmp_path / 'runs.db'
    server = create_server(path, grants=LOCAL_GRANTS)
    async with create_connected_server_and_client_session(server) as client:
        tools = (await client.list_tools()).tools
        assert {t.name for t in tools} == {'arqon_health', 'arqon_run_mock', 'arqon_propose_checklist'}
        assert all(t.inputSchema['additionalProperties'] is False for t in tools)
        health = await client.call_tool('arqon_health', {})
        assert not health.isError and health.structuredContent['prototype'] is True
        proposal = await client.call_tool('arqon_propose_checklist', {'workflow': 'travel'})
        assert not proposal.isError
        content = proposal.structuredContent
        assert set(content) == {'proposal_id', 'title', 'items', 'status'}
        assert content['status'] == 'pending_approval'
        assert content['title'] == 'Travel checklist' and len(content['items']) == 5
        assert content['proposal_id']
        result = await client.call_tool('arqon_run_mock', {'task': 'Explain Arqon OS'})
        assert not result.isError
        data = result.structuredContent
        assert data['status'] == 'completed' and data['response'].startswith('MOCK:')
    reopened = SQLiteRunStore(path)
    reopened.initialize()
    assert reopened.get_run(data['run_id']).status.value == 'completed'
    assert len(reopened.list_runs()) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('name,args,code', [
    ('unknown', {}, 'UNKNOWN_TOOL'), ('system.get_time', {}, 'UNKNOWN_TOOL'),
    ('arqon_health', {'secret': 'do-not-echo'}, 'INVALID_ARGUMENTS'),
    ('arqon_run_mock', {}, 'INVALID_ARGUMENTS'),
    ('arqon_run_mock', {'task': 1}, 'INVALID_ARGUMENTS'),
    ('arqon_run_mock', {'task': '  '}, 'INVALID_ARGUMENTS'),
    ('arqon_run_mock', {'task': 'x' * 4001}, 'INVALID_ARGUMENTS'),
    ('arqon_run_mock', {'task': 'ok', 'url': 'https://example.com'}, 'INVALID_ARGUMENTS'),
    ('arqon_run_mock', {'task': 'ok', 'grants': ['*']}, 'INVALID_ARGUMENTS'),
    ('arqon_propose_checklist', {}, 'INVALID_ARGUMENTS'),
    ('arqon_propose_checklist', {'workflow': 1}, 'INVALID_ARGUMENTS'),
    ('arqon_propose_checklist', {'workflow': 'x' * 4001}, 'INVALID_ARGUMENTS'),
    ('arqon_propose_checklist', {'workflow': 'travel', 'approved': True}, 'INVALID_ARGUMENTS'),
    ('arqon_propose_checklist', {'workflow': 'travel', 'approval_id': 'fake'}, 'INVALID_ARGUMENTS'),
    ('arqon_propose_checklist', {'workflow': 'travel', 'grants': ['*']}, 'INVALID_ARGUMENTS'),
    ('arqon_approve_checklist', {}, 'UNKNOWN_TOOL'),
    ('arqon_save_checklist', {}, 'UNKNOWN_TOOL'),
    ('safeaction.save_travel_checklist', {}, 'UNKNOWN_TOOL'),
    ('arqon_issue_permission', {}, 'UNKNOWN_TOOL'),
    ('arqon_generate_approval', {}, 'UNKNOWN_TOOL'),
])
async def test_rejected_arguments(tmp_path, name, args, code):
    async with create_connected_server_and_client_session(create_server(tmp_path/'runs.db', grants=LOCAL_GRANTS)) as client:
        result = await client.call_tool(name, args)
        assert result.isError and result.content[0].text == code


@pytest.mark.asyncio
@pytest.mark.parametrize('grants', [frozenset(), frozenset({'*'})])
async def test_no_permission_bypass(tmp_path, grants):
    async with create_connected_server_and_client_session(create_server(tmp_path/'runs.db', grants=grants)) as client:
        for name, args in [('arqon_run_mock', {'task': 'hello'}),
                           ('arqon_propose_checklist', {'workflow': 'travel'})]:
            result = await client.call_tool(name, args)
            assert result.isError and result.content[0].text == 'PERMISSION_DENIED'


@pytest.mark.asyncio
async def test_actual_stdio_sdk_client(tmp_path):
    params = StdioServerParameters(command=sys.executable,
        args=['-B', '-m', 'arqon_os.mcp_server', '--database', str(tmp_path/'stdio.db')],
        cwd=str(ROOT), env={'PYTHONPATH': str(ROOT), 'PYTHONDONTWRITEBYTECODE': '1'})
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as client:
            initialized = await client.initialize()
            assert initialized.serverInfo.name == 'Arqon OS'
            assert initialized.capabilities.tools is not None
            assert initialized.capabilities.resources is None
            assert len((await client.list_tools()).tools) == 3
            assert not (await client.call_tool('arqon_health', {})).isError
            proposal = await client.call_tool('arqon_propose_checklist', {'workflow': 'travel'})
            assert not proposal.isError and proposal.structuredContent['status'] == 'pending_approval'


def test_malformed_stdio_messages(tmp_path):
    process = subprocess.Popen([sys.executable, '-B', '-m', 'arqon_os.mcp_server',
                                '--database', str(tmp_path/'malformed.db')],
                               cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True)
    def exchange(message):
        process.stdin.write(message + '\n'); process.stdin.flush()
        assert select.select([process.stdout], [], [], 15)[0], 'No protocol response'
        return json.loads(process.stdout.readline())
    try:
        reply = exchange('{malformed')
        # SDK reports unparseable messages (no recoverable request ID) as
        # a safe error notification; do not implement a second protocol parser.
        assert reply['jsonrpc'] == '2.0'
        assert reply['method'] == 'notifications/message'
        assert reply['params']['data'] == 'Internal Server Error'
        reply = exchange(json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
            'params': {'protocolVersion': '2025-11-25', 'capabilities': {},
                       'clientInfo': {'name': 'test', 'version': '1'}}}))
        assert 'result' in reply
        process.stdin.write('{"jsonrpc":"2.0","method":"notifications/initialized"}\n'); process.stdin.flush()
        reply = exchange('{"jsonrpc":"2.0","id":2,"method":"unknown/method"}')
        assert reply['error']['code'] == -32602  # SDK request-union validation
        reply = exchange('{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":3}}')
        assert 'error' in reply
    finally:
        process.terminate(); process.communicate(timeout=10)
