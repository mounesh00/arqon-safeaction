"""Repeatable offline workflow using the official MCP stdio client.

From the repository root:
.venv-mcp/bin/python -B -m examples.amazon_mcp_demo
"""

import asyncio
from datetime import timedelta
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from arqon_os.runtime.storage import SQLiteRunStore


def _data(result) -> dict:
    if result.isError or not isinstance(result.structuredContent, dict):
        raise RuntimeError("MCP tool did not return a successful structured result.")
    return result.structuredContent


async def demo() -> None:
    print("LOCAL MCP SIMULATOR — NOT CONNECTED TO ALEXA+")
    root = Path(__file__).resolve().parents[1]
    with TemporaryDirectory(prefix="arqon-mcp-demo-") as directory:
        database = Path(directory) / "runs.db"
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-B", "-m", "arqon_os.mcp_server", "--database", str(database)],
            cwd=str(root),
            env={"PYTHONPATH": str(root), "PYTHONDONTWRITEBYTECODE": "1"},
        )
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=30)) as client:
                initialized = await client.initialize()
                if initialized.capabilities.tools is None:
                    raise RuntimeError("Server did not negotiate tool support.")
                names = {tool.name for tool in (await client.list_tools()).tools}
                if names != {"arqon_health", "arqon_run_mock", "arqon_propose_checklist"}:
                    raise RuntimeError("Unexpected MCP tool allowlist.")
                print("Tools: " + ", ".join(sorted(names)))
                health = _data(await client.call_tool("arqon_health", {}))
                if health.get("status") != "ok" or health.get("prototype") is not True:
                    raise RuntimeError("Unexpected service health.")
                print("Health: ok (local prototype)")
                proposal = _data(await client.call_tool("arqon_propose_checklist", {"workflow": "travel"}))
                if set(proposal) != {"proposal_id", "title", "items", "status"} or proposal["status"] != "pending_approval":
                    raise RuntimeError("Unexpected checklist proposal.")
                print("Checklist: " + proposal["title"] + " (pending_approval; not saved)")
                result = _data(await client.call_tool("arqon_run_mock", {"task": "Say hello in one sentence."}))
                if (result.get("status") != "completed" or result.get("prototype") is not True
                        or not isinstance(result.get("response"), str)
                        or not result["response"].startswith("MOCK:")
                        or not isinstance(result.get("run_id"), str)):
                    raise RuntimeError("Unexpected mock agent result.")
                print("Response: " + result["response"])
                print("Run ID: " + result["run_id"])
                print("Status: " + result["status"])
        # Reopen storage after the session/subprocess closes; verify disk state.
        store = SQLiteRunStore(database)
        store.initialize()
        run = store.get_run(result["run_id"])
        if (run is None or run.status.value != result["status"] or run.error_code is not None
                or run.started_at is None or run.finished_at is None):
            raise RuntimeError("Persisted lifecycle verification failed.")
        print("Persistence: verified (lifecycle metadata only)")
    print("Cleanup: client/server closed; temporary database removed")


def main() -> int:
    try:
        asyncio.run(demo())
    except Exception:
        print("Demo failed; no external service was requested.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
