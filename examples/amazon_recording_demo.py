"""Local recording setup; no Alexa+ connection or external inference.

Run: .venv-mcp/bin/python -B -m examples.amazon_recording_demo
Prompts for a hidden independent operator password. Ctrl-C cleans owned resources.
"""

import argparse
import asyncio
import getpass
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import stat
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps/web"


def say(text):
    print(text, flush=True)


def read_password(path):
    if path is None:
        value = getpass.getpass("Independent demo operator password (16+ bytes; hidden): ")
        if value != getpass.getpass("Repeat password (hidden): "):
            raise ValueError("Password mismatch")
    else:
        # Optional automation input: existing private file, never echoed or copied.
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("Password file must be private and owned by you")
        value = path.read_text().rstrip("\r\n")
    if not 16 <= len(value.encode()) <= 1024:
        raise ValueError("Invalid password length")
    return value


async def run(args, password):
    node = shutil.which("node")
    python = Path(os.environ.get("ARQON_BACKEND_PYTHON", str(ROOT / ".venv-backend/bin/python")))
    mcp_python = Path(os.environ.get("ARQON_MCP_PYTHON", str(ROOT / ".venv-mcp/bin/python")))
    next_bin = WEB / "node_modules/next/dist/bin/next"
    if not node or not all(p.exists() for p in (python, mcp_python, next_bin)):
        raise RuntimeError("Existing demo environments unavailable")
    processes = []
    client = build_opener(ProxyHandler({}))
    backend = f"http://127.0.0.1:{args.backend_port}"
    frontend = f"http://127.0.0.1:{args.web_port}"
    with TemporaryDirectory(prefix="arqon-recording-") as directory:
        folder = Path(directory)
        os.chmod(folder, 0o700)
        database = folder / "demo.db"
        stop = folder / "STOP"
        sandbox = folder / "web"
        sandbox.mkdir()
        # Existing source and dependencies; build caches and generated files stay
        # in this disposable copy. Never load an existing repository .env file.
        for name in ("package.json", "package-lock.json", "tsconfig.json", "next-env.d.ts",
                     "next.config.ts", "postcss.config.mjs"):
            if (WEB / name).is_file():
                shutil.copy2(WEB / name, sandbox / name)
        for name in ("app", "lib", "public"):
            if (WEB / name).is_dir():
                shutil.copytree(WEB / name, sandbox / name)
        if args.production:
            if not (WEB / ".next/BUILD_ID").is_file():
                raise RuntimeError("Build frontend before production demo")
            shutil.copytree(WEB / ".next", sandbox / ".next", ignore=shutil.ignore_patterns("cache", "dev"))
        (sandbox / "node_modules").symlink_to(WEB / "node_modules", target_is_directory=True)
        # Deliberately do not pass inherited API keys/passwords to child services.
        env = {k: v for k, v in os.environ.items() if k in
               ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "SYSTEMROOT")}
        env.update(PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1",
                   NEXT_TELEMETRY_DISABLED="1", ARQON_VERIFY_BUILD="0" if args.production else "1", WATCHPACK_POLLING="true")
        key = secrets.token_urlsafe(40)
        salt = secrets.token_bytes(16)
        verifier = hashlib.scrypt(password.encode(), salt=salt, n=32768, r=8, p=3,
                                  maxmem=64 * 1024 * 1024, dklen=64)
        benv = env | {"ARQON_DATABASE_PATH": str(database), "ARQON_OPERATOR_KEY": key}
        nenv = env | {"ARQON_BACKEND_URL": backend, "ARQON_OPERATOR_ORIGIN": frontend,
                      "ARQON_OPERATOR_KEY": key, "ARQON_OPERATOR_LOGIN_HASH":
                      "scrypt:" + salt.hex() + ":" + verifier.hex()}

        def start(command, cwd, environment, name):
            path = folder / (name + ".log")
            with path.open("xb") as log:
                path.chmod(0o600)
                process = subprocess.Popen(command, cwd=cwd, env=environment,
                                           stdout=log, stderr=log, start_new_session=True)
            processes.append(process)

        def read(url, *, auth=False):
            headers = {"Authorization": "Bearer " + key} if auth else {}
            with client.open(Request(url, headers=headers), timeout=10) as response:
                return json.load(response)

        async def ready(url, expected=200):
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                if any(p.poll() is not None for p in processes):
                    raise RuntimeError("Service exited during startup")
                try:
                    # Warm compilation before creating expiring proposals.
                    with client.open(url, timeout=3) as response:
                        if response.status == expected:
                            return
                except HTTPError as error:
                    if error.code == expected:
                        return
                except (URLError, TimeoutError):
                    pass
                await asyncio.sleep(1)
            raise RuntimeError("Local startup deadline exceeded")

        try:
            start([str(python), "-B", "-m", "uvicorn", "arqon_os.api:create_app", "--factory",
                   "--host", "127.0.0.1", "--port", str(args.backend_port),
                   "--no-proxy-headers", "--no-access-log"], ROOT, benv, "backend")
            next_args = ["start"] if args.production else ["dev", "--webpack"]
            start([node, str(next_bin), *next_args, "--hostname", "127.0.0.1",
                   "--port", str(args.web_port)], sandbox, nenv, "dashboard")
            await ready(backend + "/api/v1/health")
            await ready(frontend + "/")
            # The real unauthenticated response warms the catch-all API module;
            # never disable auth or let first-login compilation consume its TTL.
            await ready(frontend + "/api/v1/operator/session", expected=401)
            parameters = StdioServerParameters(command=str(mcp_python),
                args=["-B", "-m", "arqon_os.mcp_server", "--database", str(database)],
                cwd=str(ROOT), env={"PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1"})
            with (folder / "mcp.log").open("w") as mcp_log:
                async with stdio_client(parameters, errlog=mcp_log) as (input_stream, output_stream):
                    async with ClientSession(input_stream, output_stream) as session:
                        await session.initialize()
                        tools = {tool.name for tool in (await session.list_tools()).tools}
                        if tools != {"arqon_health", "arqon_run_mock", "arqon_propose_checklist"}:
                            raise RuntimeError("Unexpected MCP tool list")
                        proposals = []
                        for _ in range(2):
                            result = await session.call_tool("arqon_propose_checklist", {"workflow": "travel"})
                            if result.isError or not isinstance(result.structuredContent, dict):
                                raise RuntimeError("Proposal creation failed")
                            proposal = result.structuredContent
                            saved = read(backend + "/api/v1/operator/proposals/" + proposal["proposal_id"], auth=True)
                            if saved["status"] != "pending" or saved["items"] != proposal["items"]:
                                raise RuntimeError("Shared proposal verification failed")
                            proposals.append(saved)
                        manifest = {"frontend": frontend, "backend": backend,
                                    "database": str(database), "proposals": proposals}
                        (folder / "demo.json").write_text(json.dumps(manifest))
                        say("LOCAL SYNTHETIC DEMO — SIMULATED ALEXA+-STYLE; NOT A LIVE ALEXA+ INTEGRATION")
                        say("Dashboard: " + frontend)
                        say("Synthetic A (approve): " + proposals[0]["proposal_id"])
                        say("Synthetic B (reject): " + proposals[1]["proposal_id"])
                        say("Both pending; expire at " + min(p["expires_at"] for p in proposals))
                        say("Public demo metadata: " + str(folder / "demo.json"))
                        say("Cleanup: Ctrl-C here, or: touch " + str(stop))
                        say("READY — log in with your independent password; record within 3 minutes.")
                        # Keep exactly one dashboard process and its sessions alive.
                        while not stop.exists():
                            if any(p.poll() is not None for p in processes):
                                raise RuntimeError("Owned service exited")
                            await asyncio.sleep(1)
        finally:
            for process in reversed(processes):
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=20)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
    say("CLEANUP COMPLETE — owned services stopped; demo database, logs and temporary configuration removed.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend-port", type=int, default=8100)
    parser.add_argument("--web-port", type=int, default=3210)
    parser.add_argument("--production", action="store_true", help="Use an existing production build")
    parser.add_argument("--password-file", type=Path,
                        help="Optional existing private password file for local verification; never printed")
    args = parser.parse_args()
    if (args.backend_port == args.web_port or
            any(not 1024 <= p <= 65535 for p in (args.backend_port, args.web_port))):
        parser.error("Choose two distinct unprivileged local ports")
    try:
        asyncio.run(run(args, read_password(args.password_file)))
    except KeyboardInterrupt:
        say("Demo stopped; owned resources cleaned up.")
    except Exception:
        say("Demo failed; owned resources cleaned up. Check prerequisites and unused ports.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
