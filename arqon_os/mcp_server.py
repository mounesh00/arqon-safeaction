"""Official MCP SDK stdio adapter. No HTTP listener or real inference.

Launching grants health.read, agent.mock.run and checklist.propose only.
It does not approve or dispatch any local/security tool. Database lifecycle
writes are internal and the database path is configured only by the operator.
"""

import argparse
import asyncio
import logging
from pathlib import Path

from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, TextContent, Tool, ToolAnnotations

from arqon_os.agents.basic import BasicAgent
from arqon_os.gateway.gateway import ModelGateway
from arqon_os.gateway.provider import MockModelProvider
from arqon_os.runtime.engine import AgentRuntime
from arqon_os.runtime.storage import SQLiteRunStore
from arqon_os.safe_action import PersistentSafeActionWorkflow
from arqon_os.tools.approvals import ApprovalManager
from arqon_os.tools.permissions import PermissionEngine
from arqon_os.tools.registry import RiskLevel, ToolDefinition, ToolRegistry

LOCAL_GRANTS = frozenset({"health.read", "agent.mock.run", "checklist.propose"})


def create_server(database_path: Path, *, grants: frozenset[str] = frozenset()) -> Server:
    """Explicit construction initializes the existing store; imports do not."""
    store = SQLiteRunStore(database_path)
    store.initialize()
    gateway = ModelGateway()
    gateway.register_provider("mock", MockModelProvider())
    agent = BasicAgent(AgentRuntime(store), gateway)
    # No human deciders and no approval/save handlers or grants are exposed.
    workflow = PersistentSafeActionWorkflow(database_path, ApprovalManager())
    workflow.initialize()
    registry = ToolRegistry()
    for name, permission, description in (
        ("arqon_health", "health.read", "Local Arqon OS service information."),
        ("arqon_run_mock", "agent.mock.run", "Prototype mock agent; persists run lifecycle only."),
        ("arqon_propose_checklist", "checklist.propose", "Prepare a travel checklist pending human review; never approve or save."),
    ):
        registry.register(ToolDefinition(name, description, "mcp", RiskLevel.LOW,
                                         frozenset({permission})))
    server = Server("Arqon OS", version="0.1.0", instructions="Local mock prototype. No real AI or tools.")

    @server.list_tools()
    async def list_tools():
        return [Tool(
            name=tool.name, description=tool.description,
            inputSchema={"type": "object", "additionalProperties": False,
                         "properties": {} if tool.name == "arqon_health" else {
                             "workflow": {"type": "string", "enum": ["travel"], "maxLength": 16}}
                         if tool.name == "arqon_propose_checklist" else {
                             "task": {"type": "string", "minLength": 1, "maxLength": 4000}},
                         "required": [] if tool.name == "arqon_health" else
                         ["workflow"] if tool.name == "arqon_propose_checklist" else ["task"]},
            annotations=ToolAnnotations(readOnlyHint=tool.name == "arqon_health",
                                        destructiveHint=False, openWorldHint=False),
        ) for tool in registry.list_tools()]

    def error(code):
        return CallToolResult(isError=True, content=[TextContent(type="text", text=code)])

    # Validate ourselves to avoid SDK JSON-schema errors echoing user inputs.
    @server.call_tool(validate_input=False)
    async def call_tool(name, arguments):
        if name not in ("arqon_health", "arqon_run_mock", "arqon_propose_checklist"):
            return error("UNKNOWN_TOOL")
        if type(arguments) is not dict:
            return error("INVALID_ARGUMENTS")
        if name == "arqon_health":
            if arguments:
                return error("INVALID_ARGUMENTS")
        elif name == "arqon_propose_checklist":
            if (set(arguments) != {"workflow"} or type(arguments["workflow"]) is not str
                    or arguments["workflow"] != "travel"):
                return error("INVALID_ARGUMENTS")
        elif (set(arguments) != {"task"} or type(arguments["task"]) is not str
              or not arguments["task"].strip() or len(arguments["task"]) > 4000):
            return error("INVALID_ARGUMENTS")
        if not PermissionEngine().evaluate(registry.get(name), grants).allowed:
            return error("PERMISSION_DENIED")
        try:
            if name == "arqon_health":
                return {"application": "Arqon OS", "version": "0.1.0", "status": "ok",
                        "provider": "mock", "prototype": True}
            if name == "arqon_propose_checklist":
                proposal = workflow.prepare()
                return {"proposal_id": proposal.proposal_id, "title": proposal.title,
                        "items": list(proposal.items), "status": "pending_approval"}
            result = agent.run(arguments["task"])
            if result.error_code:
                return error(result.error_code)
            return {"run_id": result.run_id, "status": result.status.value,
                    "response": result.response, "prototype": True}
        except Exception:
            return error("INTERNAL_ERROR")

    return server


async def serve(database_path: Path) -> None:
    server = create_server(database_path, grants=LOCAL_GRANTS)
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path(".arqon-os/arqon.db"))
    args = parser.parse_args()
    # SDK malformed-message diagnostics can contain client input; keep them out
    # of stderr. stdout is reserved exclusively for SDK protocol messages.
    logging.getLogger("mcp").disabled = True
    logging.disable(logging.CRITICAL)
    asyncio.run(serve(args.database))


if __name__ == "__main__":
    main()
