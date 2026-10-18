"""Run from the repository: python3 -m examples.basic_agent_demo."""

from pathlib import Path
from tempfile import TemporaryDirectory

from arqon_os.agents import BasicAgent
from arqon_os.gateway.gateway import ModelGateway
from arqon_os.gateway.provider import MockModelProvider
from arqon_os.runtime.engine import AgentRuntime
from arqon_os.runtime.storage import SQLiteRunStore


def main() -> None:
    with TemporaryDirectory(prefix="arqon-agent-") as directory:
        store = SQLiteRunStore(Path(directory) / "runs.db")
        store.initialize()
        gateway = ModelGateway()
        gateway.register_provider("mock", MockModelProvider())
        result = BasicAgent(AgentRuntime(store), gateway).run("Say hello in one sentence.")
        print(f"Run ID: {result.run_id}")
        print(f"Status: {result.status.value}")
        print(f"Response: {result.response}")


if __name__ == "__main__":
    main()
