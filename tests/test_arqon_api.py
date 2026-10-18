import socket
import sys

import pytest
from fastapi.testclient import TestClient

from arqon_os.api import create_app, MAX_BODY_BYTES
from arqon_os.gateway.provider import MockModelProvider


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*args, **kwargs):
        pytest.fail("External connection forbidden")
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(socket, "getaddrinfo", deny)
    # No tool or legacy imports are needed by the API.
    class BlockTools:
        def find_spec(self, fullname, *args):
            if fullname.startswith(("architect_vapt", "arqon_os.tools", "arqon_os.capabilities")):
                raise AssertionError("Tool/scanner import")
    guard = BlockTools()
    sys.meta_path.insert(0, guard)
    yield
    sys.meta_path.remove(guard)


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / "runs.db"), base_url="http://127.0.0.1") as client:
        yield client


def test_health(client):
    response = client.get("/api/v1/health")
    assert response.json() == {"status": "ok", "application": "Arqon OS", "api_version": "v1"}
    assert "access-control-allow-origin" not in response.headers


def test_success_restart(tmp_path):
    path = tmp_path / "runs.db"
    app = create_app(path)
    assert not path.exists()
    with TestClient(app, base_url="http://127.0.0.1") as client:
        response = client.post("/api/v1/agent/run", json={"task": "Explain Arqon OS"})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed" and data["response"].startswith("MOCK:")
        saved = client.get("/api/v1/agent/runs/" + data["run_id"]).json()
        assert saved["status"] == "completed"
        assert saved["created_at"] <= saved["updated_at"]
        assert "response" not in saved
    with TestClient(create_app(path), base_url="http://127.0.0.1") as restarted:
        assert restarted.get("/api/v1/agent/runs/" + data["run_id"]).json() == saved


@pytest.mark.parametrize("body", ['{', '[]', '{}', '{"task":""}', '{"task":"  "}',
    '{"task":1}', '{"task":"a","model":"other"}', '{"task":"a","task":"b"}',
    '{"task":"' + 'a' * 4001 + '"}'])
def test_invalid(client, body):
    assert client.post("/api/v1/agent/run", content=body,
                       headers={"content-type": "application/json"}).status_code == 400


def test_body_limit(client):
    assert client.post("/api/v1/agent/run", content=b"x" * (MAX_BODY_BYTES + 1),
                       headers={"content-type": "application/json"}).status_code == 413


def test_missing_and_no_tools(client):
    assert client.get("/api/v1/agent/runs/missing").status_code == 404
    assert client.post("/api/v1/tools/execute", json={}).status_code == 404
    assert client.post("/api/v1/security/recon", json={}).status_code == 404
    assert client.post("/api/v1/agent/run", content="task=x").status_code == 415
    assert client.get("/api/v1/health", headers={"origin": "https://other.example"}).status_code == 403


def test_provider_failure(client, monkeypatch):
    def fail(*args):
        raise RuntimeError("API_KEY=secret")
    monkeypatch.setattr(MockModelProvider, "generate", fail)
    response = client.post("/api/v1/agent/run", json={"task": "hello"})
    assert response.status_code == 502 and "secret" not in response.text
    data = response.json()
    saved = client.get("/api/v1/agent/runs/" + data["run_id"]).json()
    assert saved["status"] == "failed" and saved["error_code"] == "AGENT_MODEL_FAILED"
