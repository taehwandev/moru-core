"""Offline, host/source-bound native artifact transport.

Owner: explicit portable archive validation and local artifact publication.
Allowed imports: stdlib only. Forbidden: compiler, network, global configuration.
Callers/tests: native-runtime-bundle.py; test_native_bundle.
"""
from __future__ import annotations

import hashlib
import gzip
import io
import json
import os
from pathlib import Path
import platform
import tarfile
import tempfile

_BINARIES = ("moru-checkout-identity", "moru-native-launcher")
_MANIFEST = "manifest.json"
_MAX_BYTES = 32 * 1024 * 1024
_MAX_MANIFEST = 128 * 1024


def _host() -> dict[str, str]:
    system = {"Darwin": "macos", "Linux": "linux"}.get(platform.system())
    arch = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x86_64",
            "amd64": "x86_64"}.get(platform.machine().lower())
    if system is None or arch is None:
        raise ValueError("native bundles support macOS/Linux arm64 and x86_64 only")
    return {"os": system, "arch": arch}


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sources(root: Path) -> dict[str, str]:
    package = root / "native/checkout-identity"
    rust = sorted((package / "src").rglob("*.rs"))
    if not rust:
        raise ValueError("native source tree is missing")
    return {str(p.relative_to(root)): _digest(p.read_bytes())
            for p in [package / "Cargo.toml", package / "Cargo.lock", *rust]}


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate manifest key")
        result[key] = value
    return result


def _json(data: bytes) -> dict:
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=_object)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("invalid bundle JSON") from error
    if not isinstance(value, dict):
        raise ValueError("bundle JSON must be an object")
    return value


def _validate_manifest(root: Path, manifest: dict, payloads: dict[str, bytes]) -> None:
    if set(manifest) != {"schema_version", "platform", "rustc", "source_sha256", "artifacts"}:
        raise ValueError("invalid manifest fields")
    if type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1:
        raise ValueError("unsupported bundle schema")
    if manifest["platform"] != _host():
        raise ValueError("bundle platform does not match this host")
    if not isinstance(manifest["rustc"], str) or not 0 < len(manifest["rustc"]) <= 512:
        raise ValueError("invalid compiler metadata")
    if manifest["source_sha256"] != _sources(root):
        raise ValueError("bundle sources do not match this checkout")
    artifacts = manifest["artifacts"]
    if not isinstance(artifacts, dict) or set(artifacts) != set(_BINARIES):
        raise ValueError("invalid bundle artifacts")
    for name in _BINARIES:
        entry = artifacts[name]
        if not isinstance(entry, dict) or set(entry) != {"bytes", "sha256"}:
            raise ValueError("invalid artifact metadata")
        if (type(entry["bytes"]) is not int or entry["bytes"] <= 0
                or entry["bytes"] != len(payloads[name]) or entry["sha256"] != _digest(payloads[name])):
            raise ValueError("bundle artifact hash or size mismatch")


def _read_bundle(archive: Path) -> tuple[dict, dict[str, bytes]]:
    if archive.stat().st_size >= _MAX_BYTES:
        raise ValueError("bundle exceeds archive limit")
    with archive.open("rb") as stream:
        raw = stream.read(_MAX_BYTES)
    if len(raw) >= _MAX_BYTES:
        raise ValueError("bundle exceeds archive limit")
    try:
        if raw.startswith(b"\x1f\x8b"):
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
                raw = stream.read(_MAX_BYTES)
        if len(raw) >= _MAX_BYTES:
            raise ValueError("bundle exceeds expanded size limit")
    except (OSError, EOFError) as error:
        raise ValueError("invalid compressed bundle") from error
    contents = {}
    total = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as bundle:
            for member in bundle:
                if (member.name not in (_MANIFEST, *_BINARIES) or member.name in contents
                        or member.type not in (tarfile.REGTYPE, tarfile.AREGTYPE)
                        or member.size < 0 or member.size >= _MAX_BYTES):
                    raise ValueError("unexpected or unsafe bundle member")
                total += member.size
                if total >= _MAX_BYTES or (member.name == _MANIFEST and member.size > _MAX_MANIFEST):
                    raise ValueError("bundle exceeds expanded size limit")
                stream = bundle.extractfile(member)
                if stream is None:
                    raise ValueError("unreadable bundle member")
                data = stream.read(member.size + 1)
                if len(data) != member.size:
                    raise ValueError("truncated bundle member")
                contents[member.name] = data
    except (tarfile.TarError, EOFError) as error:
        raise ValueError("invalid bundle archive") from error
    if set(contents) != {_MANIFEST, *_BINARIES}:
        raise ValueError("bundle members are incomplete")
    manifest = _json(contents.pop(_MANIFEST))
    return manifest, contents


def pack_bundle(root: Path, archive: Path) -> dict:
    """Package an already verified local build; never compile or download."""
    root = root.resolve()
    state = root / ".moru/native"
    receipt = _json((state / "build.json").read_bytes())
    payloads, artifacts = {}, {}
    for name, entry in ((_BINARIES[0], receipt), (_BINARIES[1], receipt.get("launcher"))):
        path = state / "bin" / name
        if path.is_symlink() or not path.is_file() or not os.access(path, os.X_OK):
            raise ValueError("native build artifact is missing or unsafe")
        if path.stat().st_size >= _MAX_BYTES or not isinstance(entry, dict):
            raise ValueError("invalid build artifact")
        payloads[name] = path.read_bytes()
        artifacts[name] = {"bytes": entry.get("bytes"), "sha256": entry.get("sha256")}
    manifest = {"schema_version": 1, "platform": _host(), "rustc": receipt.get("rustc"),
                "source_sha256": receipt.get("source_sha256"), "artifacts": artifacts}
    _validate_manifest(root, manifest, payloads)
    contents = {_MANIFEST: (json.dumps(manifest, sort_keys=True) + "\n").encode(), **payloads}
    if sum(map(len, contents.values())) >= _MAX_BYTES:
        raise ValueError("bundle exceeds expanded size limit")
    archive = archive.absolute()
    protected = {state / "build.json", *(state / "bin" / n for n in _BINARIES)}
    if archive in protected:
        raise ValueError("archive cannot replace a native build input")
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".native-pack-", dir=archive.parent) as directory:
        temporary = Path(directory) / "bundle.tar.gz"
        with tarfile.open(temporary, "w:gz") as bundle:
            for name, data in contents.items():
                member = tarfile.TarInfo(name)
                member.size, member.mode = len(data), 0o755 if name in _BINARIES else 0o644
                bundle.addfile(member, io.BytesIO(data))
        if temporary.stat().st_size >= _MAX_BYTES:
            raise ValueError("bundle exceeds archive limit")
        temporary.replace(archive)
    return manifest


def install_bundle(root: Path, archive: Path) -> dict:
    """Validate everything, then publish binaries and finally their receipt."""
    root = root.resolve()
    manifest, payloads = _read_bundle(archive)
    _validate_manifest(root, manifest, payloads)
    state = root / ".moru/native"
    paths = [root / ".moru", state, state / "bin", state / "build.json",
             *(state / "bin" / name for name in _BINARIES)]
    if any(path.is_symlink() for path in paths):
        raise ValueError("native installation path must not be a symlink")
    state.mkdir(parents=True, exist_ok=True)
    (state / "bin").mkdir(exist_ok=True)
    records = {name: {"binary": str(state / "bin" / name), **manifest["artifacts"][name]}
               for name in _BINARIES}
    receipt = {**records[_BINARIES[0]], "launcher": records[_BINARIES[1]],
               "rustc": manifest["rustc"], "source_sha256": manifest["source_sha256"]}
    with tempfile.TemporaryDirectory(prefix=".native-install-", dir=state) as directory:
        stage = Path(directory)
        for name, data in payloads.items():
            path = stage / name
            path.write_bytes(data)
            path.chmod(0o755)
        receipt_path = stage / "build.json"
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
        # Retire the old receipt before any binary replacement. A publication
        # failure cannot leave a stale receipt authorizing a mixed build.
        previous = state / "build.json"
        if previous.exists():
            previous.replace(stage / "previous-build.json")
        for name in _BINARIES:
            (stage / name).replace(state / "bin" / name)
        receipt_path.replace(state / "build.json")
    return receipt
