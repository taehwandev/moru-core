//! owner: bounded read-only wait for path claim contention.
//! allowed imports: path claim scan and system clocks.
//! forbidden imports: claim writes and expiry cleanup.
//! callers/tests: path_claims CLI; test_path_claims wait parity.
//! verification: deadline, conflict release, and legacy fallback.
use super::path_claim_scan::PathClaimScan;
use serde_json::{json, Value};
use std::{
    thread,
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};

// Keep each probe below the host transport's ten-second deadline.
const WAIT_BUDGET: Duration = Duration::from_secs(8);

pub(super) struct PathClaimWait;

impl PathClaimWait {
    pub(super) fn probe(input: &Value) -> Option<Value> {
        let deadline = input.get("deadline")?.as_f64()?;
        let now = Self::now()?;
        // Older callers supplied only short wall-clock deadlines.
        let compatible_clock = match input.get("observed_at") {
            Some(sample) => (sample.as_f64()? - now).abs() <= 2.0,
            None => deadline > now && deadline - now <= WAIT_BUDGET.as_secs_f64(),
        };
        if !compatible_clock {
            return None;
        }
        let mut remaining = deadline - now;
        let started = Instant::now();
        while remaining > 0.0 {
            let budget_left = WAIT_BUDGET.saturating_sub(started.elapsed());
            thread::sleep(Duration::from_secs_f64(remaining.clamp(0.05, 1.0)).min(budget_left));
            let Some(now) = Self::now() else { break };
            remaining = deadline - now;
            // The host still makes the final acquisition attempt at the deadline.
            if remaining <= 0.0 || started.elapsed() >= WAIT_BUDGET {
                break;
            }
            let Some(result) = PathClaimScan::probe(input) else {
                break;
            };
            let conflicts = &result["conflicts"];
            let Some(now) = Self::now() else { break };
            if !conflicts["earliest"]
                .as_f64()
                .is_some_and(|expiry| expiry > now)
                || !conflicts["matches"]
                    .as_array()
                    .is_some_and(|matches| !matches.is_empty())
            {
                break;
            }
            remaining = deadline - now;
        }
        Some(json!({"waited": true}))
    }

    fn now() -> Option<f64> {
        Some(
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .ok()?
                .as_secs_f64(),
        )
    }
}
