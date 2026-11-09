---
keyflow_id: sys_native_pretool_diff_queries
status: review
type: ai-generated
---

# Native pretool Git diff queries

This single bounded follow-up moves ordinary Git diff classification onto the
existing native pretool path for both Claude and Codex. It does not execute Git
or change the Python policy. The full-inventory automatic goal remains paused.

Supported forms include plain `git diff`, an optional leading `--cached`, one
existing display/check selector, and optional literal paths after `--`.
Selectors are `--stat`, `--check`, `--name-only`, `--name-status`, `--numstat`
and `--exit-code`. Paths may contain ordinary letters/digits, Unicode, spaces,
underscores, dots, hyphens and slashes. Existing absolute `-C`, scoped output
filters, source/environment checks and Codex transcript binding still apply.

Unknown options, unsafe or abbreviated output/execution flags, leading option
paths, Git magic/glob pathspecs, parent traversal and unsupported shell syntax
retain Python handling. Local executable shadows and exceptional transcript or
path contexts preserve the original callback results. No permission or write
capability is added. Remaining full pretool migration stays open in units20/24.

## Evidence

Six baseline cases showed that the original Python callbacks allowed these
queries while the prior native callbacks required Python replay. After the
change, 21 ordinary diff forms across both callbacks match Python with Python
and Git absent from PATH. Eighteen unsafe/unsupported neighbors retain replay;
additional shadow, symlink-error and transcript cases compare original results.

The focused Git/pretool/query suite passed all 34 Python cases. Four Rust query
tests passed, including the three existing tests moved into a dedicated test
file and one new diff grammar test. The transported macOS ARM64 bundle passed
199 checks, with four new plain/cached-path diff callback checks on empty PATH.
Only synthetic project/transcript fixtures are used. No timing or token-savings
claim is added; cross-host acceptance is not inferred from local results.

Actual installation is checked separately after exact main integration. This
batch does not request a remote build, push, tag or release.
