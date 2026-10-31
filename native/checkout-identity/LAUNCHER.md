---
keyflow_id: sys_native_launcher_bridge
status: review
type: ai-generated
---

# Native launcher bridge: migration stage two

The stable launcher selects an optional verified native ingress. The new
`checkout-identity` command serves the existing NDJSON contract directly in
Rust. Every other command, including lifecycle aliases and help, execs the
same self-contained Python launcher body with unchanged arguments, stdin,
working directory and environment. No policy decision moves in this stage.

The exact trusted launcher alias is classified as read-only for no arguments
or --help. Unknown arguments and impostor executable paths do not inherit that
classification. Shell output targets remain visible to existing raw-path
validation; lookup itself does not require a writable task.

Owner: native command ingress. Allowed imports: Rust std and CheckoutIdentity;
installer/build stdlib. Forbidden: networking, credentials, lifecycle writes,
new policy exceptions and automatic global installation.

## Interface and rollback

Internal binary interface: `moru-native-launcher PYTHON_LAUNCHER [ARGS...]`.
The internal path is supplied by the stable trampoline before unchanged user
arguments. Unix exec preserves the process boundary: legacy commands launch
one Python interpreter, not a Python child of another interpreter.

`checkout-identity` accepts stdin NDJSON and no operational arguments;
`--help` succeeds and other arguments fail with exit 2. It preserves
`MORU_CHECKOUT_IDENTITY_BACKEND=auto|rust|python`; python forwards to the
compatibility command. Request errors remain protocol responses. Stream I/O
failures return nonzero. MORU_HOOK_SOFT_FAIL retains its existing exit-code
behavior. Failure to launch the Python interpreter returns 127.

The installed trampoline uses `MORU_LAUNCHER_BACKEND=auto|rust|python`.
Auto sends only the native lookup alias through Rust, avoiding an additional
native exec for commands still owned by Python. Forced rust exercises the
generic legacy forwarding path too. Unknown values fail with exit 2, missing
forced native returns 127, and a
missing optional native executable uses Python. A native execution failure
propagates; consumed input is never replayed. Explicit Python invocation of
the trampoline remains valid through its shell/Python polyglot header.

Only a locally built native artifact whose receipt matches its bytes and
current Cargo/runtime sources can be selected during setup. Without it the
original Python launcher is generated. Dry runs mutate nothing, stale builds
fall back safely, and the existing durable-root downgrade guard runs first.

Verification installs into temporary homes only. Existing user-global hooks,
permissions, root pointers and runtime settings are not installed or changed
by this work. Native absence and Python rollback remain supported. Other
operating systems and full Rust migration of legacy policy are not claimed.

## Verified result

Verification covers 124 distinct Python tests and eight Rust tests: a full
123-case Python run plus two focused inventory checks after adding the broader
coverage case. Production inputs were unchanged by that documentation/test
extension. Temporary-home
checks cover actual native execution with no Python or toolchain on PATH,
stdio/arguments/cwd/environment/PID preservation, legacy exits and signals,
soft fail, native absence, forced rollback, idempotent setup, dry runs, stale
source receipts, tampered binaries and current-source checksum validation.
Native/Python help and backend error behavior agree. Simple path-helper import
does not load the installer or template; a regression check pins that boundary.
The compatibility body matches baseline 1a61f4be plus one lookup alias exactly.
Inventory coverage checks 30 primary owners plus 22 ancillary CLIs, all 52
unique execution units, without duplicate aliases or executing the tools.

Actual generated launcher medians on this macOS arm64 host, in milliseconds:

| Case | Auto bridge | Forced native ingress | Python reference |
| --- | ---: | ---: | ---: |
| Checkout lookup | 9.9810 | 9.5087 | 67.0261 |
| Synthetic legacy dispatch | 41.0105 | 42.3664 | 38.1214 |

Thirty fresh samples per mode/case, randomized sequential order, warm filesystem
and prepared Python bytecode. Setup, compilation and parent JSON validation
are excluded. The legacy case is a minimal fixture, not a full policy hook.
The auto bridge adds about 2.889 ms to this legacy reference; it does not make
the remaining Python processors faster. Optional activation and explicit
rollback are retained. No whole-Core or token-cost speedup is claimed.

Raw samples and p95 values are retained in ignored
`.moru/native/launcher-benchmark.json`. The earlier eager-import profile is
separate; these runs do not isolate import cost causally from host variation.
The optimized native ingress executable is 510,560 bytes on this host.

Reproduce after the offline runtime build:

```sh
PYTHONPATH=scripts:tests python3 -B -m unittest test_native_stable_launcher test_stable_launcher test_stable_launcher_help test_setup_agent_hooks test_runtime_setup_ownership_boundary test_checkout_identity_runtime test_build_native_runtime test_claude_worktree_gate_git_dir test_claude_worktree_gate
CARGO_TARGET_DIR="$PWD/.moru/native/cargo-target" cargo test --locked --offline --manifest-path native/checkout-identity/Cargo.toml
python3 -B tests/benchmarks/native_launcher_entrypoint.py
```
