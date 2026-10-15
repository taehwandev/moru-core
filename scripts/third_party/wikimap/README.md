---
keyflow_id: sys_third_party_wikimap
status: stable
type: human-reviewed
---

# Wikimap Third-Party Source

This directory contains a repository-pinned copy of Wikimap used
only by `scripts/workflow_wikimap.py` for deterministic document indexing and
search.

- Upstream: <https://github.com/dhha22/wikimap>
- Version: `v1.5.0`
- Commit: `ede03cd8ddb545b6b538237509516948fdf00174`
- `wikimap.py` SHA-256:
  `0322cd07037f33d8f7a42a84ced4ba8a10bc9d3829cc4b0faea4b1a566c4ea4d`
- License: MIT; see `LICENSE`.

## Integration Boundary

Moru Core invokes only:

1. `update --no-map` to refresh the local `.wikimap/` cache.
2. `search --json` to retrieve document sections.

Do not wire Wikimap `install`, `--hook`, source-editing, or semantic-note
commands into Moru Core. Hooks remain read-only enforcement points.

The bundled source removes the former graph-tool import and migration
commands, their skill installer, and the obsolete generated-output exclusion.
The upstream version and commit above identify the baseline; the checksum
identifies these reviewed local bytes.

## Upgrade Verification

When upgrading, replace `wikimap.py` and `LICENSE` from one reviewed upstream
tag, reapply the documented local removals, update the version, commit, and checksum in `workflow_wikimap.py` and this
file, then run the upstream test suite plus Moru Core routing tests,
`workflow.py validate`, and VibeGuard.
