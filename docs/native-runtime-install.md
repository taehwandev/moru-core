---
keyflow_id: sys_native_runtime_portable_install
status: review
type: ai-generated
---

# Install a prebuilt native runtime

Moru Core still requires Python 3.9+ and Git. Its checkout lookup and normal
Claude/Antigravity status rendering can use two optional Rust executables.
Receiving computers do not need Rust or Cargo when installing a matching bundle.
Keep the Python fallback; unusual status inputs may require it.

## Obtain the matching build

The [Native runtime bundles workflow](../.github/workflows/native-runtime.yml)
builds macOS ARM64, macOS x86_64, Linux x86_64 and Linux ARM64 separately. It
runs on main when native/build inputs change, or manually on main. Each job
builds pinned Rust 1.94.1 with locked crates, runs behavioral checks, packs the
two binaries and verifies transport into a fresh source root and temporary home
with an empty PATH. An artifact is uploaded only after those checks pass.

Download the matching `moru-native-<platform>-<commit>` artifact from a successful
trusted main workflow run and unzip it to obtain its `.tar.gz`. GitHub artifact
downloads require sign-in/read access and expire after seven days; a new manual
build restores availability. This is a development distribution path, not an
anonymous permanent release URL or a claim that every matrix host has passed.
The run records each host's actual result. No tag/release is created automatically.

macOS bundles target macOS 13+ and are tested on the selected macOS 15 runners.
Linux bundles are built/tested on Ubuntu 24.04; older glibc distributions are not
established compatible. Windows is not supported by this POSIX native runtime.
Do not infer performance on these hosts from the local Mac benchmark.

## Install after updating source

Update your existing Moru Core checkout to the reviewed main revision using
your normal Git workflow; preserve local edits. From that root:

```sh
python3 scripts/native-runtime-bundle.py install --bundle /path/to/moru-native-macos-arm64.tar.gz
python3 scripts/setup-agent-hooks.py --dry-run
python3 scripts/setup-agent-hooks.py
python3 scripts/setup-agent-hooks.py --check
```

Select your own platform's bundle. Installation validates the host, exact native
source hashes and both binary sizes/hashes before writing ignored local state.
It rejects extra, duplicate, linked or traversing tar members, malformed JSON,
oversized data and symlink installation paths. No shell extraction, compiler,
network, runtime configuration or credential access occurs during bundle import.
Setup then refreshes the existing connections and root pointer while preserving
configured renderer chains and Spill integration. Follow repo-local setup rules
when selecting runtimes; inspect the dry run first.

Hashes check integrity and source matching, not publisher authenticity. Obtain
the bundle from a trusted workflow; do not execute arbitrary matching manifests.
If validation fails, existing artifacts remain unchanged. An I/O failure during
publication removes the receipt, so a mixed installation cannot be authorized;
retry a known-good bundle. Missing or stale native artifacts retain Python
operation. `MORU_LAUNCHER_BACKEND=python` explicitly rolls back the launcher;
`MORU_CHECKOUT_IDENTITY_BACKEND=python` rolls back the direct checkout adapter.

## Build and transport locally

Developers with an installed Rust toolchain and cached locked crates can build
and pack without downloading tools:

```sh
python3 scripts/build_native_runtime.py
python3 scripts/native-runtime-bundle.py pack --bundle /path/to/moru-native-bundle.tar.gz
PYTHONPATH=scripts:tests python3 -B tests/smoke_native_bundle.py --bundle /path/to/moru-native-bundle.tar.gz
```

The transport smoke verifies checkout identity and both statuslines through the
generated launcher with no Python, Rust, Cargo or Git on PATH. It does not alter
your actual home. A successful temporary-home check is distinct from installing
and checking the actual user-level runtime on the receiving computer.
