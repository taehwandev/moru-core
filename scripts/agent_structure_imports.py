"""Import extraction and pattern matching for structure rule checks."""

from __future__ import annotations

import fnmatch
import posixpath
import re
from pathlib import Path


BARE_IMPORT_RE = re.compile(
    r"^\s*(?:@[A-Za-z_]\w*(?:\([^)]*\))?\s+)*"
    r"(?:(?:public|package|internal|fileprivate|private)\s+)?"
    r"import\s+"
    r"(?:(?:static|struct|class|enum|protocol|actor|typealias|func|var|let)\s+)?"
    r"([A-Za-z_][\w.]*(?:\.\*)?)(?:;|\s|$)"
)
IMPORT_RE = (
    re.compile(r"^\s*import\s+(?:type\s+)?(?:[^\"']+\s+from\s+)?[\"']([^\"']+)[\"']"),
    re.compile(r"^\s*export\s+(?:type\s+)?[^\"']+\s+from\s+[\"']([^\"']+)[\"']"),
    re.compile(r"\brequire\(\s*[\"']([^\"']+)[\"']\s*\)"),
    re.compile(r"\bimport\(\s*[\"']([^\"']+)[\"']\s*\)"),
    re.compile(r"^\s*from\s+([A-Za-z_][\w.]*|\.+[\w.]*)\s+import\b"),
    BARE_IMPORT_RE,
    re.compile(r"^\s*use\s+([A-Za-z_][\w:]*)(?:;|\s|$)"),
)


def imports_for_path(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []
    imports: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "//", "/*", "*")):
            continue
        quoted_import_found = False
        for pattern in IMPORT_RE:
            if quoted_import_found and pattern is BARE_IMPORT_RE:
                continue
            match = pattern.search(line)
            if not match:
                continue
            spec = match.group(1).strip()
            if spec and spec not in imports:
                imports.append(spec)
            if "\"" in line or "'" in line:
                quoted_import_found = True
    return imports


def import_candidates(spec: str, source_path: Path) -> set[str]:
    candidates = {spec}
    suffix = source_path.suffix.lower()
    if spec.startswith("."):
        candidates.add(posixpath.normpath(posixpath.join(source_path.parent.as_posix(), spec)))
    elif suffix == ".dart" and not spec.startswith(("dart:", "package:")) and ":" not in spec:
        candidates.add(posixpath.normpath(posixpath.join(source_path.parent.as_posix(), spec)))
    if spec.startswith("package:"):
        candidates.add(spec[len("package:"):])
    if "." in spec:
        candidates.add(spec.replace(".", "/"))
        if suffix == ".swift":
            candidates.add(spec.split(".", 1)[0])
    if "::" in spec:
        candidates.add(spec.replace("::", "/"))
    if spec.startswith("@/"):
        candidates.add("src/" + spec[2:])
    return {candidate.strip("/") for candidate in candidates if candidate}


def should_check_allowed_import(
    spec: str,
    candidates: set[str],
    project_prefixes: list[str],
    allow_external: bool,
) -> bool:
    if not allow_external:
        return True
    if spec.startswith("."):
        return True
    return bool(project_prefixes and any(matches_any(candidate, project_prefixes) for candidate in candidates))


def matches_any(value: str, patterns: list[str]) -> bool:
    return any(matches_one(value, pattern) for pattern in patterns)


def matches_one(value: str, pattern: str) -> bool:
    value = value.strip("/")
    pattern = pattern.strip("/")
    if fnmatch.fnmatchcase(value, pattern):
        return True
    if not any(token in pattern for token in "*?["):
        return value == pattern or value.startswith(pattern + "/")
    return False
