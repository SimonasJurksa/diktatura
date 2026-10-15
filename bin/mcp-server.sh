#!/usr/bin/env bash
# Diktatūra — MCP serveris (stdio) AI klientams, pvz. Claude Code:
#   claude mcp add diktatura -- <repo>/bin/mcp-server.sh        (make mcp parodo tikslią komandą)
# TIK SKAITO tekstus (paieška, sesijos, kas kiek kalbėjo). Pats niekur nejungia — bet ką klientas perskaito, patenka
# į jo pokalbį (debesų AI — į jo debesį). Žr. diktatura/mcp_server.py.
REPO="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
export PYTHONPATH="$REPO${PYTHONPATH:+:$PYTHONPATH}"
exec /usr/bin/python3 -m diktatura.mcp_server "$@"
