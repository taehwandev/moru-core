"""Spellings Moru Core used before it was renamed from Tao Agent OS.

Owner: the pre-rename vocabulary, kept in one place; imports: none;
callers: setup cleanup (removing what an older setup wrote), the local-state
migration and project-pointer tools, and the scans that must skip a leftover
state directory. Runtime behaviour never selects these names: nothing here is
read as configuration or written as new state.
"""

from __future__ import annotations

# State directory, launcher and root pointer of the old install.
STATE_DIR = ".tao"
LAUNCHER = "tao-hook"
ROOT_POINTER = "tao-root"
ENV_PREFIX = "TAO_"
CHECKOUT_DIR = "tao-agent-os"

# Managed markers an older setup wrote into files it owns.
ROUTING_BEGIN = "<!-- BEGIN MANAGED TAO AGENT OS ROUTING -->"
ROUTING_END = "<!-- END MANAGED TAO AGENT OS ROUTING -->"
STATUSLINE_MARKER = "TAO_STATUSLINE=1"
HOOK_SOFT_FAIL = "TAO_HOOK_SOFT_FAIL=1"
CLAUDE_AGENT_MARKER = "# Tao Agent OS managed Claude agent"
CODEX_AGENT_MARKER = "# Tao Agent OS managed Codex agent"
AGENT_NAMES = ("tao_explorer", "tao_worker", "tao_reviewer")
RULES_BLOCK_NAME = "tao-hooks"
WORKSPACE_PROFILE = "tao-workspace"
WORKSPACE_DESCRIPTION = 'description = "Workspace access plus the shared Tao Agent OS runtime."'
LAUNCH_AGENT_LABEL = "com.taehwandev.tao-agent-os.maintenance"
BACKUP_SUFFIX = ".tao-backup"
GRAPHIFY_CHECKOUT_MARKER = "# tao-graphify-checkout:v1"
