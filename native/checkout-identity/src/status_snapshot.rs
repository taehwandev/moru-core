//! Canonical status aggregation and dynamic metadata; no state or authority writes.
//! Owner: status snapshot formatting. Allowed: serde_json and std/libc.
//! Forbidden: lifecycle policy, persistence, model calls and contract duplication.
//! Callers/tests: StatusProcess; Rust vectors and Python status/API parity.
//! Verification: exact sorted JSON, UUID4/UTC shapes and unusual-value fallback.
use serde_json::Value;
use std::{collections::BTreeMap, fs::File, io::Read, time::SystemTime};

mod contract {
    include!(concat!(env!("OUT_DIR"), "/status_contract.rs"));
}

pub(crate) struct StatusSnapshot;

impl StatusSnapshot {
    pub(crate) fn capture_time() -> Option<String> {
        let elapsed = SystemTime::now()
            .duration_since(SystemTime::UNIX_EPOCH)
            .ok()?;
        timestamp(elapsed.as_secs().try_into().ok()?, elapsed.subsec_micros())
    }

    pub(crate) fn render(
        values: &[Value; 3],
        captured: &str,
        present: [bool; 2],
        validated: bool,
    ) -> Option<String> {
        let (active, tasks, events) = Self::aggregate(values)?;
        let mut bytes = [0; 16];
        File::open("/dev/urandom")
            .ok()?
            .read_exact(&mut bytes)
            .ok()?;
        let snapshot = format!(
            "{{\"active_runs\": {active}, \"api_contract\": {}, \"api_version\": {}, \
             \"captured_at\": {}, \"consistency\": \"project-state-lock\", \"events\": {events}, \
             \"registry_present\": {}, \"runtime_adapters\": {}, \"scheduler_present\": {}, \
             \"snapshot_id\": \"{}\", \"task_counts\": {tasks}}}",
            contract::API,
            contract::VERSION,
            serde_json::to_string(captured).ok()?,
            present[0],
            contract::ADAPTERS,
            present[1],
            uuid(bytes),
        );
        Some(if validated {
            format!("{{\"failures\": [], \"snapshot\": {snapshot}, \"valid\": true}}\n")
        } else {
            snapshot + "\n"
        })
    }

    pub(crate) fn supported(values: &[Value; 3]) -> bool {
        Self::aggregate(values).is_some()
    }

    fn aggregate(values: &[Value; 3]) -> Option<(usize, String, String)> {
        let mut active = 0;
        for run in rows(&values[0], "runs").iter().filter(|v| v.is_object()) {
            match run.get("state") {
                Some(Value::String(s)) if matches!(s.as_str(), "running" | "paused") => active += 1,
                None | Some(Value::Null | Value::String(_)) => {}
                _ => return None,
            }
        }
        Some((
            active,
            counts(rows(&values[1], "tasks"), "state", false)?,
            counts(rows(&values[2], "events"), "event_type", true)?,
        ))
    }
}

fn rows<'a>(value: &'a Value, key: &str) -> &'a [Value] {
    value
        .get(key)
        .and_then(Value::as_array)
        .map(Vec::as_slice)
        .unwrap_or(&[])
}

fn counts(values: &[Value], key: &str, skip_nonobjects: bool) -> Option<String> {
    let mut result = BTreeMap::new();
    for item in values {
        if !item.is_object() && skip_nonobjects {
            continue;
        }
        let object = item.as_object()?;
        let label = match object.get(key) {
            Some(Value::String(s)) if !s.is_empty() => s.as_str(),
            None | Some(Value::Null | Value::String(_)) => "unknown",
            _ => return None,
        };
        *result.entry(label).or_insert(0u64) += 1;
    }
    Some(format!(
        "{{{}}}",
        result
            .into_iter()
            .map(|(key, count)| format!("{}: {count}", serde_json::to_string(key).unwrap()))
            .collect::<Vec<_>>()
            .join(", ")
    ))
}

fn uuid(mut bytes: [u8; 16]) -> String {
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

fn timestamp(seconds: libc::time_t, micros: u32) -> Option<String> {
    if micros >= 1_000_000 {
        return None;
    }
    let mut utc = std::mem::MaybeUninit::<libc::tm>::uninit();
    if unsafe { libc::gmtime_r(&seconds, utc.as_mut_ptr()) }.is_null() {
        return None;
    }
    let utc = unsafe { utc.assume_init() };
    let year = utc.tm_year.checked_add(1900)?;
    if !(1..=9999).contains(&year) {
        return None;
    }
    let fraction = if micros == 0 {
        String::new()
    } else {
        format!(".{micros:06}")
    };
    Some(format!(
        "{year:04}-{:02}-{:02}T{:02}:{:02}:{:02}{fraction}+00:00",
        utc.tm_mon + 1,
        utc.tm_mday,
        utc.tm_hour,
        utc.tm_min,
        utc.tm_sec
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn metadata_keeps_python_isoformat_and_uuid4_bits() {
        assert_eq!(timestamp(0, 0).unwrap(), "1970-01-01T00:00:00+00:00");
        assert_eq!(
            timestamp(951782400, 42).unwrap(),
            "2000-02-29T00:00:00.000042+00:00"
        );
        assert_eq!(
            timestamp(0, 999999).unwrap(),
            "1970-01-01T00:00:00.999999+00:00"
        );
        assert!(timestamp(0, 1000000).is_none());
        assert_eq!(uuid([0; 16]), "00000000000040008000000000000000");
        assert_eq!(uuid([255; 16]), "ffffffffffff4fffbfffffffffffffff");
    }

    #[test]
    fn count_maps_sort_unicode_and_reject_python_specific_values() {
        let values =
            serde_json::json!([{"state":"한글"},{"state":"a"},{"state":"a"},{"state":""},{}]);
        assert_eq!(
            counts(values.as_array().unwrap(), "state", false).unwrap(),
            "{\"a\": 2, \"unknown\": 2, \"한글\": 1}"
        );
        for value in [
            serde_json::json!([null]),
            serde_json::json!([{"state":5}]),
            serde_json::json!([{"state":[]}]),
        ] {
            assert!(counts(value.as_array().unwrap(), "state", false).is_none());
        }
        assert_eq!(counts(&[Value::Null], "event_type", true).unwrap(), "{}");
    }
}
