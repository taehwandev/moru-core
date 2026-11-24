//! owner: deterministic review-packet section budgeting and digest.
//! allowed imports: source-bound stdin/stdout, ordered JSON and SHA-256.
//! forbidden imports: source reads, Git, provider calls and review verdicts.
//! callers/tests: ReviewAssembly and native packet parity fixtures.
//! verification: exact bytes, whole sections and omissions in priority order.
use crate::pretool_guard::CallbackGuard;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    collections::HashSet,
    ffi::OsString,
    io::{self, Read, Write},
};

const MAX_MESSAGE: usize = 1024 * 1024;
const BUCKETS: [&str; 5] = ["diffs", "definitions", "contexts", "contracts", "findings"];

struct Section<'a> {
    bucket: &'a str,
    path: &'a str,
    body: &'a Value,
    omission: &'a Value,
}

pub(crate) struct ReviewPacketAssembly;

impl ReviewPacketAssembly {
    pub(crate) fn run(launcher: &OsString, args: &[OsString]) -> i32 {
        if args.len() != 2
            || args[1] != "assemble"
            || CallbackGuard::root(launcher, "review-packet").is_none()
        {
            return 125;
        }
        let mut raw = Vec::new();
        if io::stdin()
            .take((MAX_MESSAGE + 1) as u64)
            .read_to_end(&mut raw)
            .is_err()
            || raw.len() > MAX_MESSAGE
        {
            return 125;
        }
        let Some(result) = serde_json::from_slice::<Value>(&raw)
            .ok()
            .filter(integral_json)
            .and_then(Self::build)
        else {
            return 125;
        };
        let Ok(reply) = serde_json::to_vec(&json!({"schema_version": 1, "result": result})) else {
            return 125;
        };
        if reply.len() > MAX_MESSAGE {
            return 125;
        }
        i32::from(io::stdout().write_all(&reply).is_err())
    }

    fn build(mut input: Value) -> Option<Value> {
        let mut packet = input.get_mut("packet")?.take();
        if packet["kind"] != "review_packet"
            || packet["schema_version"] != 1
            || packet["context_only"] != true
            || packet["no_execution"] != true
            || packet["packet_sha256"].as_str()? != "0".repeat(64)
            || BUCKETS.iter().any(|bucket| {
                packet[*bucket]
                    .as_array()
                    .is_none_or(|rows| !rows.is_empty())
            })
        {
            return None;
        }
        let max_bytes = usize::try_from(packet["max_bytes"].as_u64()?).ok()?;
        if !(2048..=MAX_MESSAGE).contains(&max_bytes) {
            return None;
        }
        let pending = input.get("pending")?.as_array()?;
        if pending.len() > 128 {
            return None;
        }
        let pending: Vec<_> = pending.iter().map(section).collect::<Option<_>>()?;
        let mut fixed = input.get("fixed")?.as_array()?.clone();
        let added: HashSet<_> = packet["files"]
            .as_array()?
            .iter()
            .filter(|file| file["status"] == "added")
            .map(|file| file["path"].as_str().map(str::to_owned))
            .collect::<Option<_>>()?;
        let mut kept = vec![false; pending.len()];
        if packet_size(&mut packet, &pending, &fixed, &kept)? > max_bytes {
            return Some(
                json!({"error": "max_bytes is too small for the packet metadata and omissions"}),
            );
        }
        let mut kept_diffs = HashSet::new();
        for (index, section) in pending.iter().enumerate() {
            kept[index] = true;
            if matches!(section.bucket, "definitions" | "contracts")
                && added.contains(section.path)
                && kept_diffs.contains(section.path)
            {
                let mut omission = section.omission.clone();
                omission["reason"] = json!("covered_by_diff");
                fixed.push(omission);
                continue;
            }
            packet[section.bucket]
                .as_array_mut()?
                .push(section.body.clone());
            if packet_size(&mut packet, &pending, &fixed, &kept)? > max_bytes {
                kept[index] = false;
                packet[section.bucket].as_array_mut()?.pop();
            } else if section.bucket == "diffs" {
                kept_diffs.insert(section.path);
            }
        }
        if packet_size(&mut packet, &pending, &fixed, &kept)? > max_bytes {
            return Some(json!({"error": "review packet metadata exceeds its output budget"}));
        }
        let mut body = packet.clone();
        body.as_object_mut()?.remove("packet_sha256");
        packet["packet_sha256"] = json!(format!("{:x}", Sha256::digest(render(body)?)));
        Some(json!({"packet": packet}))
    }
}

fn section(row: &Value) -> Option<Section<'_>> {
    let [bucket, body, omission] = row.as_array()?.as_slice() else {
        return None;
    };
    let bucket = bucket.as_str()?;
    (BUCKETS.contains(&bucket) && omission.is_object()).then_some(Section {
        bucket,
        path: body.get("path")?.as_str()?,
        body,
        omission,
    })
}

fn packet_size(
    packet: &mut Value,
    pending: &[Section<'_>],
    fixed: &[Value],
    kept: &[bool],
) -> Option<usize> {
    packet["omissions"] = Value::Array(
        fixed
            .iter()
            .cloned()
            .chain(
                pending
                    .iter()
                    .zip(kept)
                    .filter(|(_, kept)| !**kept)
                    .map(|(section, _)| section.omission.clone()),
            )
            .collect(),
    );
    Some(render(packet.clone())?.len())
}

fn render(mut value: Value) -> Option<String> {
    value.sort_all_objects();
    let text = serde_json::to_string_pretty(&value).ok()?;
    let mut output = String::with_capacity(text.len() + 1);
    for line in text.lines() {
        // JSON string newlines are escaped; only formatter indentation is physical.
        let spaces = line.len() - line.trim_start_matches(' ').len();
        output.push_str(&line[spaces / 2..]);
        output.push('\n');
    }
    Some(output)
}

fn integral_json(value: &Value) -> bool {
    match value {
        Value::Number(number) => !number.is_f64(),
        Value::Array(rows) => rows.iter().all(integral_json),
        Value::Object(fields) => fields.values().all(integral_json),
        _ => true,
    }
}
