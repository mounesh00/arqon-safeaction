"""Local single-operator mock API. See docs/AMAZON_DEMO.md.

Importing does not initialize storage. No model selection or tool execution is
exposed over HTTP. Public hosting requires additional security controls.
"""

from contextlib import asynccontextmanager
from dataclasses import asdict
import hmac
import ipaddress
import json
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from arqon_os.agents.basic import BasicAgent
from arqon_os.gateway.gateway import ModelGateway
from arqon_os.gateway.provider import MockModelProvider
from arqon_os.runtime.engine import AgentRuntime, RunNotFoundError
from arqon_os.runtime.storage import SQLiteRunStore
from arqon_os.safe_action import (
    PersistentSafeActionWorkflow, ProposalNotFoundError, ProposalConflictError,
)
from arqon_os.tools.approvals import (
    ApprovalManager, ActorKind, ApprovalBindingError, ApprovalExpiredError,
)

MAX_BODY_BYTES = 24 * 1024


def _error(status: int, code: str) -> JSONResponse:
    return JSONResponse({"error": code}, status_code=status)


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError()
        result[key] = value
    return result


def create_app(database_path: Path | None = None) -> FastAPI:
    database_path = Path(database_path if database_path is not None else
                         os.environ.get("ARQON_DATABASE_PATH", ".arqon-os/arqon.db"))
    store = SQLiteRunStore(database_path)
    runtime = AgentRuntime(store)
    gateway = ModelGateway()
    gateway.register_provider("mock", MockModelProvider())
    agent = BasicAgent(runtime, gateway)
    operator_key = os.environ.get("ARQON_OPERATOR_KEY", "")
    configured = (32 <= len(operator_key) <= 256
                  and all(33 <= ord(c) < 127 for c in operator_key))
    workflow = PersistentSafeActionWorkflow(database_path,
        ApprovalManager(frozenset({"local-operator"}) if configured else frozenset()))

    @asynccontextmanager
    async def lifespan(app):
        store.initialize()
        workflow.initialize()
        yield

    app = FastAPI(title="Arqon OS", version="v1", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])

    @app.middleware("http")
    async def safe_boundary(request, call_next):
        # Reject cross-origin browser calls; no CORS allowance is installed.
        if request.headers.get("origin") is not None:
            return _error(403, "ORIGIN_NOT_ALLOWED")
        try:
            response = await call_next(request)
        except Exception:
            return _error(500, "INTERNAL_ERROR")
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/v1/health")
    def health():
        return {"status": "ok", "application": "Arqon OS", "api_version": "v1"}

    @app.post("/api/v1/agent/run")
    async def run_agent(request: Request):
        if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            return _error(415, "JSON_REQUIRED")
        if request.headers.get("content-encoding", "identity") != "identity":
            return _error(415, "ENCODING_NOT_SUPPORTED")
        length = request.headers.get("content-length")
        if length is not None:
            if not length.isdecimal():
                return _error(400, "INVALID_REQUEST")
            if int(length) > MAX_BODY_BYTES:
                return _error(413, "BODY_TOO_LARGE")
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > MAX_BODY_BYTES:
                return _error(413, "BODY_TOO_LARGE")
            body.extend(chunk)
        try:
            value = json.loads(body.decode("utf-8"), object_pairs_hook=_object)
            if (type(value) is not dict or set(value) != {"task"}
                    or type(value["task"]) is not str or not value["task"].strip()
                    or len(value["task"]) > 4000):
                raise ValueError()
        except (ValueError, UnicodeError, RecursionError):
            return _error(400, "INVALID_REQUEST")
        result = await run_in_threadpool(agent.run, value["task"])
        data = {"run_id": result.run_id, "status": result.status.value, "response": result.response}
        if result.error_code:
            data["error_code"] = result.error_code
        return JSONResponse(data, status_code=502 if result.error_code else 200)

    @app.get("/api/v1/agent/runs/{run_id}")
    def get_run(run_id: str):
        try:
            run = runtime.get_run(run_id)
        except RunNotFoundError:
            return _error(404, "RUN_NOT_FOUND")
        return {"run_id": run.run_id, "status": run.status.value,
                "task_name": run.task_name, "created_at": run.created_at,
                "updated_at": run.finished_at or run.started_at or run.created_at,
                "started_at": run.started_at, "finished_at": run.finished_at,
                "error_code": run.error_code}

    def operator_auth(request: Request):
        # Reject proxy assertions entirely, including when Uvicorn would parse
        # them into request.client. Deploy locally with --no-proxy-headers.
        if any(name == b"forwarded" or name == b"x-real-ip" or name.startswith(b"x-forwarded-")
               for name, _ in request.scope["headers"]):
            return _error(403, "LOCAL_OPERATOR_ONLY")
        try:
            if request.client is None or not ipaddress.ip_address(request.client.host).is_loopback:
                return _error(403, "LOCAL_OPERATOR_ONLY")
        except ValueError:
            return _error(403, "LOCAL_OPERATOR_ONLY")
        if not configured:
            return _error(503, "OPERATOR_AUTH_UNCONFIGURED")
        auth = request.headers.getlist("authorization")
        expected = ("Bearer " + operator_key).encode("utf-8")
        if len(auth) != 1 or not hmac.compare_digest(auth[0].encode("utf-8"), expected):
            return _error(401, "OPERATOR_AUTH_REQUIRED")
        return None

    @app.get("/api/v1/operator/proposals/{proposal_id}")
    def get_proposal(proposal_id: str, request: Request):
        denied = operator_auth(request)
        if denied is not None:
            return denied
        try:
            return asdict(workflow.get_proposal(proposal_id))
        except ProposalNotFoundError:
            return _error(404, "PROPOSAL_NOT_FOUND")
        except ApprovalBindingError:
            return _error(409, "PROPOSAL_INTEGRITY_FAILED")

    async def decide(proposal_id: str, request: Request, approve: bool):
        denied = operator_auth(request)
        if denied is not None:
            return denied
        if request.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json":
            return _error(415, "JSON_REQUIRED")
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > 256:
                return _error(413, "BODY_TOO_LARGE")
            body.extend(chunk)
        try:
            data = json.loads(body.decode("utf-8"), object_pairs_hook=_object)
            if (type(data) is not dict or set(data) != {"fingerprint"}
                    or type(data["fingerprint"]) is not str or len(data["fingerprint"]) != 64
                    or any(c not in "0123456789abcdef" for c in data["fingerprint"])):
                raise ValueError()
        except (ValueError, UnicodeError, RecursionError):
            return _error(400, "INVALID_REQUEST")
        try:
            proposal = await run_in_threadpool(workflow.decide_proposal, proposal_id,
                fingerprint=data["fingerprint"], approve=approve, decided_by="local-operator",
                actor_kind=ActorKind.HUMAN, human_confirmed=True,
                grants=frozenset({"checklist.save"}))
            return asdict(proposal)
        except ProposalNotFoundError:
            return _error(404, "PROPOSAL_NOT_FOUND")
        except ApprovalBindingError:
            return _error(409, "PROPOSAL_INTEGRITY_FAILED")
        except ApprovalExpiredError:
            return _error(409, "PROPOSAL_EXPIRED")
        except ProposalConflictError:
            return _error(409, "PROPOSAL_NOT_PENDING")

    @app.post("/api/v1/operator/proposals/{proposal_id}/approve")
    async def approve_proposal(proposal_id: str, request: Request):
        return await decide(proposal_id, request, True)

    @app.post("/api/v1/operator/proposals/{proposal_id}/reject")
    async def reject_proposal(proposal_id: str, request: Request):
        return await decide(proposal_id, request, False)

    return app
