---
keyflow_id: sys_project_discovery_scan_performance
status: review
type: ai-generated
---

# Project discovery: directory enumeration

## Bounded outcome

Reduce project-discovery latency on file-heavy local trees without changing
which projects are found or selected. Baseline is `2b9655f2`; delivery remains
the dedicated performance branch. This increment keeps Python and replaces
only child-directory enumeration, not BFS, marker probes, registry handling,
ranking, search scope, depth/visit limits or default search roots.

The reference sorts all child Paths and calls `Path.is_dir()` for each visible,
non-skipped entry. The helper uses `os.scandir`, checks the same names, follows
directory symlinks, and sorts only accepted directory names before making
Paths. Directory-entry type information can avoid file-by-file metadata probes
on the tested local filesystem. Filesystems without that information and
symlink-heavy workloads can retain much of the original cost.

Owner: `support.project_directory_scan.child_directories` owns enumeration;
`agent_project_search.iter_child_dirs` is its adapter. Allowed imports: stdlib
os/pathlib. Forbidden: registry, marker, ranking and traversal policy, network,
cache or persistent state. Callers/tests: `scan_project_roots`,
`discover_projects`, `test_project_directory_scan`, `test_agent_project_discovery`.
Verification: real filesystem and synthetic-error tests, frozen-source output
comparison and actual generated-entrypoint timings below.

## Behavior and collaborators

Claude supplied the 44-line helper from a generic contract. AGY reviewed error
boundaries, stable Unicode ordering, symlinks and measurement dilution; its
response is design review, not executed verification. The lead integrated the
adapter, wrote tests and performed all measurements. Briefs contained no
repository source or private registry/search data.

Tests preserve dot-name/exact skip filtering, stable `name.lower()` ordering
(including equal keys and Unicode variants), lexical relative paths,
directory links, dangling/self links, missing/file parents, whole-enumeration
errors that discard partial results, per-entry errors that skip one child,
non-OSError propagation, BFS depth and visit-budget prefixes. Case-colliding
names use synthetic entries because the tested macOS volume is case-insensitive.
The first fixture attempted both `build` and `Build`; that fixture was corrected
before the passing run. No production repair was needed for that test failure.
The focused run passed 10 new enumeration tests and 15 existing discovery
tests, plus two inventory checks. This increment needs no Rust rebuild or
unrelated full regression rerun.

## Measurement

macOS 27.0.1 arm64, Python 3.9.6. Both variants use the same actual generated
launcher in a temporary HOME, changing only the source root. Baseline scripts
and project markers are frozen; bytecode is prepared separately. Explicit
synthetic registry/search roots prevent scans of private configured locations.
Each fresh process must have identical stdout, stderr and exit status. The
initialized scan separately checks identical ordered project paths.

Fixtures: small is 8 directories with 3 ordinary files each; file-heavy is 40
directories with 250 files each; directory-heavy is 300 directories. Every
fourth directory has AGENTS.md. Hidden/build/dependency directories are also
present and excluded. Depth-zero uses the file-heavy tree with enumeration
disabled by the existing depth rule. Warm filesystem and an unreserved host
apply; setup, tree creation and bytecode preparation are outside timing.

Initial batch: 30 randomized paired samples per variant/workload. Times are
milliseconds, **median / p95**:

| Workload | Reference fresh CLI | Candidate fresh CLI | Reference initialized scan | Candidate initialized scan |
| --- | ---: | ---: | ---: | ---: |
| Small | 103.7778 / 147.7060 | 106.9014 / 148.2625 | 1.3954 / 3.8253 | 1.3460 / 3.5879 |
| File-heavy | 151.3039 / 167.4828 | 99.0906 / 109.3508 | 55.6024 / 63.4492 | 10.8658 / 14.0382 |
| Directory-heavy | 170.5791 / 252.5581 | 182.5096 / 261.2932 | 39.0109 / 48.2230 | 38.8019 / 49.2906 |
| Depth-zero control | 84.2041 / 96.1658 | 83.9225 / 94.4439 | 0.1300 / 0.2762 | 0.1223 / 0.2908 |

File-heavy fresh latency saves **52.21 ms (34.5%)**, exceeding 20% and 5 ms;
all 30 paired runs are faster. Initialized scanning improves about **80.5%**.
This is an enumeration/CLI result, not faster arbitrary local content search,
a complete project-discovery rewrite, or a whole-agent/token saving.

The initial directory-heavy CLI median is **11.93 ms slower** despite a nearly
unchanged initialized scan. Small is 3.12 ms slower. These results were retained,
not hidden. Paired median differences are +2.46 ms and +0.43 ms respectively,
showing that a difference of marginal medians can exaggerate a noisy host run.
That does not establish the cause or prove absence of regression.

A focused follow-up used 40 pairs on those two workloads, with equal A/B and
B/A order counts shuffled across rounds. No runtime code changed:

| Recheck | Reference fresh CLI | Candidate fresh CLI | Reference initialized scan | Candidate initialized scan |
| --- | ---: | ---: | ---: | ---: |
| Small | 93.4573 / 114.6479 | 92.1828 / 113.1481 | 1.2408 / 4.3787 | 1.0626 / 3.9071 |
| Directory-heavy | 186.5514 / 278.8893 | 185.9541 / 254.3548 | 39.3569 / 46.2585 | 36.8993 / 47.7450 |

Those fresh differences are below the 5 ms target. Keep the first batch and
recheck separate; the claim is **file-heavy improvement**, with no demonstrated
material small/directory-heavy CLI gain. There is no consistent fresh regression
across these two batches, but host variability and the initialized directory
tail remain visible. Network/FUSE, cold-cache behavior, live call frequency and
resource use remain unmeasured.

## Reproduction and adoption

```sh
PYTHONPATH=scripts:tests python3 -B -m unittest test_project_directory_scan test_agent_project_discovery
PYTHONPATH=scripts:tests python3 -B tests/benchmark_project_discovery.py --baseline-revision 2b9655f2 --samples 30
```

The benchmark reads Git objects into a temporary baseline without changing
branches/worktrees or fetching anything. Current reproduction uses balanced
randomized pair order; the original batch used random order per pair. Use
`--case small --case directory_heavy` for a focused recheck. `--baseline-root`
can reuse the retained, hash-verified snapshot. Run timing before concurrent
tests/builds and outside process/filesystem sandbox instrumentation.

Ignored local records are `.moru/performance/project-discovery.json` (initial)
and `project-discovery-recheck.json` (follow-up), including raw samples, source
hashes, entrypoint hash, environment and ordered-output checks. They are local
execution evidence; the benchmark regenerates portable results from Git.

Decision: keep the measured Python optimization on the performance branch.
No new dependency, binary build, Locate integration, daemon or runtime model
call is required. Main integration, real global installation and release remain
separate later decisions. The 52-unit inventory is unchanged.
