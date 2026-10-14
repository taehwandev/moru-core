"""Update current project integration pointers after the Moru Core move.

Only known root instruction and runtime configuration files are touched.
Historical documents and product code are intentionally outside this tool.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from support import legacy_names

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
_OLD_CHECKOUT = legacy_names.CHECKOUT_DIR
_OLD_LAUNCHER = f"{legacy_names.STATE_DIR}/bin/{legacy_names.LAUNCHER}"
REPLACEMENTS = (
    (f"https://github.com/taehwandev/{_OLD_CHECKOUT}", "https://github.com/taehwandev/moru-core"),
    (f"{HOME}/git/{_OLD_CHECKOUT}", f"{HOME}/git/moru-core"),
    (f"$HOME/git/{_OLD_CHECKOUT}", "$HOME/git/moru-core"),
    (f"~/git/{_OLD_CHECKOUT}", "~/git/moru-core"),
    (f"/Users/.../{_OLD_CHECKOUT}", "/Users/.../moru-core"),
    (f".agents/{_OLD_CHECKOUT}", ".agents/moru-core"),
    (f"{HOME}/{_OLD_LAUNCHER}", f"{HOME}/.moru/bin/moru-hook"),
    (f"~/{_OLD_LAUNCHER}", "~/.moru/bin/moru-hook"),
    (f"$HOME/{_OLD_LAUNCHER}", "$HOME/.moru/bin/moru-hook"),
    (legacy_names.ROUTING_BEGIN, "<!-- BEGIN MANAGED MORU CORE ROUTING -->"),
    (legacy_names.ROUTING_END, "<!-- END MANAGED MORU CORE ROUTING -->"),
    (f"<{legacy_names.ENV_PREFIX}LAUNCHER>", "<MORU_LAUNCHER>"),
    (f"<{legacy_names.ENV_PREFIX}ROOT>", "<MORU_ROOT>"),
    (f"${{{legacy_names.ENV_PREFIX}HOME}}", "${MORU_HOME}"),
    (f"${legacy_names.ENV_PREFIX}HOME", "$MORU_HOME"),
    (legacy_names.HOOK_SOFT_FAIL, "MORU_HOOK_SOFT_FAIL=1"),
    (f"/{legacy_names.STATE_DIR}/worktrees", "/.moru/worktrees"),
    (f"cd {legacy_names.STATE_DIR}/worktrees", "cd .moru/worktrees"),
    ("Tao Agent OS", "Moru Core"),
)


def updated_text(text: str) -> str:
    for before, after in REPLACEMENTS:
        text = text.replace(before, after)
    return text


def without_duplicate_toml_keys(text: str) -> str:
    """Drop a repeated key a rename produced inside one TOML table.

    Renaming `<repo>/.tao/worktrees` to `<repo>/.moru/worktrees` collides with
    the Moru root setup already added, and TOML rejects a key defined twice,
    which stops the runtime from loading its configuration. The first
    definition stays.
    """
    seen: set[str] = set()
    kept: list[str] = []
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith("["):
            seen = set()
        elif "=" in stripped and not stripped.startswith("#"):
            key = stripped.split("=", 1)[0].strip()
            if key in seen:
                continue
            seen.add(key)
        kept.append(line)
    return "".join(kept)


def update_files(root: Path, names: tuple[str, ...], *, apply: bool) -> list[Path]:
    changed: list[Path] = []
    for name in names:
        path = root / name
        if not path.is_file() or path.is_symlink():
            continue
        original = path.read_bytes()
        text = updated_text(original.decode("utf-8"))
        if path.suffix == ".toml":
            text = without_duplicate_toml_keys(text)
        replacement = text.encode("utf-8")
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
