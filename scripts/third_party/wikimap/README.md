---
keyflow_id: sys_third_party_wikimap
status: stable
type: human-reviewed
---

# Wikimap Third-Party Source

This directory contains an unmodified, repository-pinned copy of Wikimap used
only by `scripts/workflow_wikimap.py` for deterministic document indexing and
search.

- Upstream: <https://github.com/dhha22/wikimap>
- Version: `v1.0.0`
- Commit: `9c26d7b66322741532ede0b474f0e5106643f275`
- `wikimap.py` SHA-256:
  `1e81848539ad959d90c15441b08cc95073619331afe4562f3960808f755970e9`
- License: MIT; see `LICENSE`.

## Integration Boundary

Moru Core invokes only:

1. `update --no-map` to refresh the local `.wikimap/` cache.
2. `search --json` to retrieve document sections.

Do not wire Wikimap `install`, `--hook`, `migrate`, source-editing, semantic
note, or Graphify-import commands into Moru Core. Hooks remain read-only
enforcement points, and Graphify remains the target-project code and
relationship graph.

## Upgrade Verification

When upgrading, replace `wikimap.py` and `LICENSE` from one reviewed upstream
tag, update the version, commit, and checksum in `workflow_wikimap.py` and this
file, then run the upstream test suite plus Moru Core routing tests,
`workflow.py validate`, and VibeGuard.
