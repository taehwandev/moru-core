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

pub(super) struct PathClaimWait;

impl PathClaimWait {
    pub(super) fn probe(input: &Value) -> Option<Value> {
        let deadline = input.get("deadline")?.as_f64()?;
        let mut remaining = deadline - Self::now()?;
        if !(0.0 < remaining && remaining <= 8.0) {
            return None;
        }
        let started = Instant::now();
        loop {
            thread::sleep(Duration::from_secs_f64(remaining.clamp(0.05, 1.0)));
            let Some(now) = Self::now() else { break };
            remaining = deadline - now;
            // The host still makes the final acquisition attempt at the deadline.
            if remaining <= 0.0 || started.elapsed() >= Duration::from_secs(8) {
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
            if remaining <= 0.0 {
                break;
            }
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
