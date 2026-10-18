"""One real stdio workflow with temporary persistence and clean shutdown."""

from contextlib import asynccontextmanager
import socket
from tempfile import TemporaryDirectory

import pytest

from examples import amazon_mcp_demo as demo


@pytest.mark.asyncio
async def test_offline_demo_and_cleanup(tmp_path, monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("Unexpected network access")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(demo, "TemporaryDirectory",
                        lambda **kwargs: TemporaryDirectory(dir=tmp_path, **kwargs))
    original = demo.stdio_client
    closed = []

    @asynccontextmanager
    async def checked_client(parameters):
        assert parameters.command.endswith("python")
        assert "arqon_os.mcp_server" in parameters.args
        assert set(parameters.env) == {"PYTHONPATH", "PYTHONDONTWRITEBYTECODE"}
        # Enforce offline behavior inside the server process as well.
        parameters.args = ["-B", "-c", '''
import sys, runpy
def audit(event, args):
    # asyncio needs a local Unix socketpair for its event-loop wakeup pipe.
    if event in ("socket.connect", "socket.getaddrinfo", "socket.bind", "socket.sendto"):
        raise AssertionError("Network forbidden")
sys.addaudithook(audit)
sys.argv = ["arqon_os.mcp_server", "--database", sys.argv[1]]
runpy.run_module("arqon_os.mcp_server", run_name="__main__")
''', parameters.args[-1]]
        async with original(parameters) as streams:
            yield streams
        closed.append(True)

    monkeypatch.setattr(demo, "stdio_client", checked_client)
    await demo.demo()
    output = capsys.readouterr().out
    assert "LOCAL MCP SIMULATOR — NOT CONNECTED TO ALEXA+" in output
    assert "Tools: arqon_health, arqon_propose_checklist, arqon_run_mock" in output
    assert "pending_approval; not saved" in output
    assert "Health: ok" in output
    assert "Response: MOCK:" in output
    assert "Run ID: " in output and "Status: completed" in output
    assert "Persistence: verified" in output and "Cleanup:" in output
    assert closed == [True]
    assert list(tmp_path.iterdir()) == []
