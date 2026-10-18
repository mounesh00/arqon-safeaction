#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
BACKEND_PYTHON="${ARQON_BACKEND_PYTHON:-$PWD/.venv-backend/bin/python}"
MCP_PYTHON="${ARQON_MCP_PYTHON:-$PWD/.venv-mcp/bin/python}"
export ARQON_MCP_PYTHON="$MCP_PYTHON"
export PYTHONDONTWRITEBYTECODE=1
export NEXT_TELEMETRY_DISABLED=1
"$BACKEND_PYTHON" -B -m pytest -p no:debugging -p no:cacheprovider tests/test_safe_action.py tests/test_safe_action_bridge.py tests/test_arqon_api.py tests/test_arqon_basic_agent.py tests/test_arqon_gateway.py tests/test_arqon_runtime.py tests/test_arqon_storage.py tests/test_arqon_core.py tests/test_arqon_tools.py
"$MCP_PYTHON" -B -m pytest -p no:debugging -p no:cacheprovider tests/test_arqon_mcp.py tests/test_safe_action_mcp_bridge.py tests/test_amazon_mcp_demo.py
cd apps/web
node --test scripts/operator-auth.test.mjs scripts/safe-action.test.mjs scripts/safe-action-ui.test.mjs
node node_modules/typescript/bin/tsc --noEmit --incremental false
npm run build
