"""Install Moru's thin Claude Code subagents without replacing user-owned agents.

Owner: Claude subagent setup; allowed imports: Python stdlib,
managed_agent_files; forbidden imports: workflow execution and runtime state;
callers/tests: claude_setup, test_claude_agent_setup; verification: focused
installer and template tests.
"""

from __future__ import annotations

from pathlib import Path

from support.managed_agent_files import install_managed_agents
from support import legacy_names


FRONTMATTER_FENCE = "---"
# Claude agent files must open with YAML frontmatter, so the marker cannot be
# the first line as it is for Codex; it is a YAML comment on the second line.
MANAGED_MARKER = "# Moru Core managed Claude agent"
LEGACY_MANAGED_MARKER = legacy_names.CLAUDE_AGENT_MARKER
AGENT_NAMES = ("moru_explorer", "moru_worker", "moru_reviewer")
# Role names installed before the Moru rename; setup removes their managed files.
LEGACY_AGENT_NAMES = legacy_names.AGENT_NAMES
# Sources are not stored as .md so Moru's document validators do not treat the
# Claude subagent schema as a Moru card; installed files keep the .md suffix.
SOURCE_SUFFIX = ".md.template"


def _is_managed(content: bytes) -> bool:
    """Ownership is exactly the fence followed by the marker as lines one and two."""

    lines = content.splitlines()[:2]
    return len(lines) == 2 and lines[0] == FRONTMATTER_FENCE.encode() and lines[1] in {
        MANAGED_MARKER.encode(), LEGACY_MANAGED_MARKER.encode(),
    }


def install_claude_agents(root: Path, agents_dir: Path, dry_run: bool) -> list[dict]:
    """Install namespaced subagents; source failures stop before any writes."""

    return install_managed_agents(
        template_dir=root / "templates" / "claude-agents",
        agents_dir=agents_dir,
        names=AGENT_NAMES,
        suffix=".md",
        source_suffix=SOURCE_SUFFIX,
        tool="claude",
        is_managed=_is_managed,
        dry_run=dry_run,
        legacy_names=LEGACY_AGENT_NAMES,
    )
