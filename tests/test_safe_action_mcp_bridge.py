"""MCP persistence verification in the isolated official-SDK environment."""
import socket
import pytest
from mcp.shared.memory import create_connected_server_and_client_session
from arqon_os.mcp_server import create_server, LOCAL_GRANTS
from arqon_os.safe_action import PersistentSafeActionWorkflow
from arqon_os.tools.approvals import ApprovalManager

@pytest.mark.asyncio
async def test_mcp_durable_proposal_no_decisions(tmp_path, monkeypatch):
    def deny(*args, **kwargs):
        pytest.fail('Network or decision boundary crossed')
    monkeypatch.setattr(socket.socket, 'connect', deny)
    monkeypatch.setattr(ApprovalManager, 'decide', deny)
    monkeypatch.setattr(ApprovalManager, 'consume', deny)
    path = tmp_path/'shared.db'
    async with create_connected_server_and_client_session(create_server(path, grants=LOCAL_GRANTS)) as client:
        result = await client.call_tool('arqon_propose_checklist', {'workflow':'travel'})
        assert not result.isError
        data = result.structuredContent
        assert set(data) == {'proposal_id','title','items','status'}
        assert len((await client.list_tools()).tools) == 3
        for name in ('arqon_approve_checklist','arqon_reject_checklist','arqon_save_checklist'):
            assert (await client.call_tool(name, {})).isError
    reopened = PersistentSafeActionWorkflow(path, ApprovalManager())
    reopened.initialize()
    assert reopened.get_proposal(data['proposal_id']).status == 'pending'
    assert reopened.get(data['proposal_id']) is None
