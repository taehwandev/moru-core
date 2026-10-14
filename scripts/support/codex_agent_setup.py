"""Install Moru's thin Codex roles without replacing user-owned agents.

Owner: Codex role setup; allowed imports: Python stdlib, managed_agent_files;
forbidden imports: workflow execution and runtime state; callers/tests:
setup_agent_hooks_impl, test_codex_agent_setup; verification: focused installer
and template tests.
"""

from __future__ import annotations

from pathlib import Path

from support.managed_agent_files import install_managed_agents
from support import legacy_names


MANAGED_MARKER = "# Moru Core managed Codex agent"
LEGACY_MANAGED_MARKER = legacy_names.CODEX_AGENT_MARKER
AGENT_NAMES = ("moru_explorer", "moru_worker", "moru_reviewer")
# Role names installed before the Moru rename; setup removes their managed files.
LEGACY_AGENT_NAMES = legacy_names.AGENT_NAMES


def _is_managed(content: bytes) -> bool:
    """Ownership is the marker as the exact first line."""

    lines = content.splitlines()
    return bool(lines) and lines[0] in {
        MANAGED_MARKER.encode(), LEGACY_MANAGED_MARKER.encode(),
    }


def install_codex_agents(root: Path, agents_dir: Path, dry_run: bool) -> list[dict]:
    """Install namespaced roles; source failures stop before any writes."""

    return install_managed_agents(
        template_dir=root / "templates" / "codex-agents",
        agents_dir=agents_dir,
        names=AGENT_NAMES,
        suffix=".toml",
        tool="codex",
        is_managed=_is_managed,
        dry_run=dry_run,
        legacy_names=LEGACY_AGENT_NAMES,
    )
