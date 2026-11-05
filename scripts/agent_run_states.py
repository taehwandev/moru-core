"""Canonical run-state vocabulary, without lifecycle imports.

Owner: run states. Allowed: builtins. Forbidden: I/O, policy transactions and
registry imports. Callers/tests: registry and runtime-session read adapters;
registry/session regression suites verify re-export and state behavior.
"""
ACTIVE_RUN_STATES = frozenset({"running", "paused", "resuming"})
CLAIMING_RUN_STATE = "claiming"
CLAIM_HOLDING_RUN_STATES = frozenset({*ACTIVE_RUN_STATES, CLAIMING_RUN_STATE})
RUN_STATES = frozenset(
    {
        *CLAIM_HOLDING_RUN_STATES,
        "failed",
        "completed",
        "cancelled",
        "reconcile_required",
        "blocked",
        "interrupted",
    }
)
# A run may be settled from every state that is unfinished. `blocked` and
# `interrupted` are the states a turn boundary leaves behind, and they are the
# ones a stranded run is actually found in: excluding them meant the run whose
# honest outcome was "nothing needed changing" could be cancelled only while it
# happened to be active, and the refusal was reported as an unclean checkout.
TRANSFER_CANCELLABLE_RUN_STATES = frozenset(
    {*ACTIVE_RUN_STATES, "failed", "reconcile_required", "blocked", "interrupted"}
)
# What a new request from the same runtime session settles: the claims it holds,
# the ones a turn boundary paused, and a run whose finish failed. A new request
# abandons the old request's recovery as surely as its claim; left open, the
# pre-tool gate re-binds the failed run in its checkout and refuses publication
# there with no close path. The settle records `superseded_from_state` and start
# names the failed run, so the failure is reported rather than hidden.
# `reconcile_required` stays out: it owes reconciliation of effects already made.
SUPERSEDABLE_RUN_STATES = frozenset({*ACTIVE_RUN_STATES, "blocked", "interrupted", "failed"})
# States whose owner may still append gate evidence. Recovery happens after a
# run stops being active: a failed finish must be answered by recording the
# gates it named, and a repair cycle parks the run at reconcile_required for
# the same reason. A settled run must not gain new evidence, so completed and
# cancelled are excluded.
LEDGER_WRITABLE_RUN_STATES = frozenset(
    {*ACTIVE_RUN_STATES, CLAIMING_RUN_STATE, "failed", "reconcile_required"}
)
# The complement: records that owe nothing further, so the bounded history
# below drops them first. `failed` and `reconcile_required` are not settled --
# both are states a run is recovered from, and a recovery needs its record.
SETTLED_RUN_STATES = frozenset({"completed", "cancelled"})
