"""Update current project integration pointers after the Moru Core move.

Only known root instruction and runtime configuration files are touched.
Historical documents and product code are intentionally outside this tool.
"""

from __future__ import annotations

import argparse
from pathlib import Path

FILES = (
    "AGENTS.md", "CLAUDE.md", "CODEX.md", "GEMINI.md", "VIBEGUARD.md",
    ".vibeguard.json", ".claude/settings.json",
)
HOME_FILES = (
    ".codex/AGENTS.md", ".codex/config.toml", ".claude/CLAUDE.md",
    ".claude/settings.json", ".gemini/GEMINI.md", ".antigravity/AGENTS.md",
    ".antigravitycli/AGENTS.md", ".antigravity-ide/AGENTS.md",
)
HOME = str(Path.home())
REPLACEMENTS = (
    ("https://github.com/taehwandev/tao-agent-os", "https://github.com/taehwandev/moru-core"),
    (f"{HOME}/git/tao-agent-os", f"{HOME}/git/moru-core"),
    ("$HOME/git/tao-agent-os", "$HOME/git/moru-core"),
    ("~/git/tao-agent-os", "~/git/moru-core"),
    ("/Users/.../tao-agent-os", "/Users/.../moru-core"),
    (".agents/tao-agent-os", ".agents/moru-core"),
    (f"{HOME}/.tao/bin/tao-hook", f"{HOME}/.moru/bin/moru-hook"),
    ("~/.tao/bin/tao-hook", "~/.moru/bin/moru-hook"),
    ("<!-- BEGIN MANAGED TAO AGENT OS ROUTING -->", "<!-- BEGIN MANAGED MORU CORE ROUTING -->"),
    ("<!-- END MANAGED TAO AGENT OS ROUTING -->", "<!-- END MANAGED MORU CORE ROUTING -->"),
)


def updated_text(text: str) -> str:
    for before, after in REPLACEMENTS:
        text = text.replace(before, after)
    return text


def update_files(root: Path, names: tuple[str, ...], *, apply: bool) -> list[Path]:
    changed: list[Path] = []
    for name in names:
        path = root / name
        if not path.is_file() or path.is_symlink():
            continue
        original = path.read_bytes()
        replacement = updated_text(original.decode("utf-8")).encode("utf-8")
        if replacement != original:
            changed.append(path)
            if apply:
                path.write_bytes(replacement)
    return changed


def update_project(project: Path, *, apply: bool) -> list[Path]:
    return update_files(project, FILES, apply=apply)


def update_home_configs(home: Path, *, apply: bool) -> list[Path]:
    return update_files(home, HOME_FILES, apply=apply)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--project", type=Path)
    target.add_argument("--home-config", action="store_true")
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    root = (args.project if args.project else args.home).expanduser().resolve()
    changed = (update_project(root, apply=args.apply) if args.project
               else update_home_configs(root, apply=args.apply))
    print(f"{'updated' if args.apply else 'would update'}: {len(changed)} files")
    for path in changed:
        print(path.relative_to(root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
