//! owner: runtime record retention planning; allowed: JSON, time comparison and owner probes;
//! forbidden: clocks, state file access, locks, mutations and authority;
//! callers/tests: agent_retention and native retention parity fixtures.
use super::maintenance_owner::MaintenanceOwner;
use crate::overhead_stamp::OverheadStamp;
use serde_json::{json, Value};
use std::collections::HashSet;

const MICROS_PER_DAY: i64 = 86_400_000_000;
const PYTHON_MAX_ORDINAL: i64 = 3_652_059;

pub(super) struct MaintenanceRetention;

impl MaintenanceRetention {
    pub(super) fn recover_runs(request: &Value) -> Option<Value> {
        let records = request.get("records")?.as_array()?;
        let holding = Self::strings(request.get("holding")?)?;
        let claiming = request.get("claiming")?.as_str()?;
        let cutoff = Self::ticks(request.get("cutoff")?)?;
        let ceiling = Self::ticks(request.get("ceiling")?)?;
        let mut recovered = Vec::new();
        let mut held = Vec::new();
        for (index, record) in records.iter().enumerate() {
            let record = record.as_object()?;
            let state = match record.get("state") {
                Some(Value::String(state)) if holding.contains(state.as_str()) => state,
                Some(Value::Object(_) | Value::Array(_)) => return None,
                _ => continue,
            };
            let owner = record.get(if state == claiming {
                "claim_owner"
            } else {
                "owner"
            });
            if MaintenanceOwner::recorded_pid(owner)?.is_some() && MaintenanceOwner::gone(owner)? {
                recovered.push(index);
                continue;
            }
            let updated = Self::stamp(record.get("updated_at")?)?;
            if !updated.aware() {
                return None;
            }
            let ticks = updated.ticks();
            if ticks >= cutoff {
                continue;
            }
            if ticks >= ceiling && !MaintenanceOwner::gone(owner)? {
                held.push(index);
            } else {
                recovered.push(index);
            }
        }
        Some(json!({"recovered": recovered, "held": held}))
    }

    pub(super) fn expired_runs(request: &Value) -> Option<Value> {
        let records = request.get("records")?.as_array()?;
        let settleable = Self::strings(request.get("settleable")?)?;
        let cutoff = Self::ticks(request.get("cutoff")?)?;
        let moment = Self::ticks(request.get("moment")?)?;
        let owner_window = request
            .get("owner_window")?
            .as_i64()?
            .checked_mul(1_000_000)?;
        let mut candidates = Vec::new();
        for (index, record) in records.iter().enumerate() {
            let Some(record) = record.as_object() else {
                continue;
            };
            match record.get("run_id") {
                None | Some(Value::Null) => continue,
                Some(Value::String(id)) if id.is_empty() => continue,
                Some(Value::String(_)) => {}
                _ => return None,
            }
            match record.get("state") {
                Some(Value::String(state)) if settleable.contains(state.as_str()) => {}
                Some(Value::Object(_) | Value::Array(_)) => return None,
                _ => continue,
            }
            let updated = Self::ticks(record.get("updated_at")?)?;
            // The reference compares a datetime reconstructed through a float
            // age. Outside the exact microsecond round-trip range, defer.
            if moment.abs_diff(updated) > (1 << 52)
                || !(MICROS_PER_DAY..(PYTHON_MAX_ORDINAL + 1) * MICROS_PER_DAY).contains(&updated)
            {
                return None;
            }
            if updated < cutoff
                && (moment - updated > owner_window || MaintenanceOwner::gone(record.get("owner"))?)
            {
                candidates.push(index);
            }
        }
        Some(json!({"indexes": candidates}))
    }

    pub(super) fn protected_runs(request: &Value) -> Option<Value> {
        let records = request.get("records")?.as_array()?;
        let holding = Self::strings(request.get("holding")?)?;
        let moment = Self::ticks(request.get("moment")?)?;
        let owner_window = request
            .get("owner_window")?
            .as_i64()?
            .checked_mul(1_000_000)?;
        let mut protected = Vec::new();
        for (index, record) in records.iter().enumerate() {
            let Some(record) = record.as_object() else {
                continue;
            };
            match record.get("run_id") {
                None | Some(Value::Null) => continue,
                Some(Value::String(id)) if id.is_empty() => continue,
                Some(Value::String(_)) => {}
                _ => return None,
            }
            match record.get("state") {
                Some(Value::String(state)) if holding.contains(state.as_str()) => {
                    protected.push(index);
                    continue;
                }
                Some(Value::Object(_) | Value::Array(_)) => return None,
                _ => {}
            }
            let updated = Self::ticks(record.get("updated_at")?)?;
            if moment.abs_diff(updated) > (1 << 52) {
                return None;
            }
            if moment - updated <= owner_window && !MaintenanceOwner::gone(record.get("owner"))? {
                protected.push(index);
            }
        }
        Some(json!({"indexes": protected}))
    }

    pub(super) fn plan(request: &Value) -> Option<Value> {
        let key = request.get("key")?.as_str()?;
        if !matches!(key, "runs" | "tasks" | "events") {
            return None;
        }
        let records = request.get("records")?.as_array()?;
        let cutoff = Self::ticks(request.get("cutoff")?)?;
        let limit = usize::try_from(request.get("limit")?.as_u64()?).ok()?;
        if limit == 0 {
            return None;
        }
        let terminal_states = Self::strings(request.get("terminal")?)?;
        let settled = Self::strings(request.get("settled")?)?;
        let held = Self::strings(request.get("held")?)?;
        let mut active = Vec::new();
        let mut terminal = Vec::new();
        for (index, record) in records.iter().enumerate() {
            let Some(record) = record.as_object() else {
                continue;
            };
            let timestamp = if key == "events" {
                record.get("created_at")
            } else {
                let state = record.get("state").unwrap_or(&Value::Null);
                if state.is_object() || state.is_array() {
                    return None;
                }
                let mut finished = state
                    .as_str()
                    .is_some_and(|state| terminal_states.contains(state));
                if key == "runs" {
                    let id = match record.get("run_id") {
                        None | Some(Value::Null) => "",
                        Some(value) => value.as_str()?,
                    };
                    finished = !held.contains(id) && (finished || settled.contains(id));
                }
                if !finished {
                    active.push(index);
                    continue;
                }
                match record.get("updated_at") {
                    None | Some(Value::Null) => record.get("queued_at"),
                    Some(Value::String(value)) if value.is_empty() => record.get("queued_at"),
                    Some(value) => Some(value),
                }
            };
            if Self::ticks(timestamp?)? >= cutoff {
                terminal.push(index);
            }
        }
        active.extend(terminal.iter().skip(terminal.len().saturating_sub(limit)));
        active.sort_unstable();
        Some(json!({"keep": active}))
    }

    fn strings(value: &Value) -> Option<HashSet<&str>> {
        value.as_array()?.iter().map(Value::as_str).collect()
    }

    fn ticks(value: &Value) -> Option<i64> {
        Some(Self::stamp(value)?.ticks())
    }

    pub(super) fn stamp(value: &Value) -> Option<OverheadStamp> {
        let stamp = value.as_str()?;
        let bytes = stamp.as_bytes();
        let tail = stamp.get(19..)?;
        // Only ISO shapes shared by the supported reference interpreters.
        if !stamp.is_ascii()
            || bytes[4] != b'-'
            || bytes[7] != b'-'
            || !matches!(bytes[10], b'T' | b' ')
            || bytes[13] != b':'
            || bytes[16] != b':'
            || &stamp[11..13] >= "24"
        {
            return None;
        }
        let split = tail.find(['+', '-']).unwrap_or(tail.len());
        let (fraction, offset) = tail.split_at(split);
        if !fraction.is_empty()
            && (!matches!(fraction.len(), 4 | 7)
                || !fraction.starts_with('.')
                || !fraction[1..].bytes().all(|byte| byte.is_ascii_digit()))
        {
            return None;
        }
        if !offset.is_empty()
            && (offset.len() != 6
                || &offset[1..3] >= "24"
                || offset.as_bytes()[3] != b':'
                || &offset[4..] >= "60")
        {
            return None;
        }
        OverheadStamp::parse(stamp)?
    }
}
