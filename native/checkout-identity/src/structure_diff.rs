//! owner: decoding NUL-framed Git diff observations for structural checks.
//! allowed imports: JSON and std string parsing.
//! forbidden imports: Git execution, filesystem, writes and review decisions.
//! callers/tests: structural review and preview via private completion probe.
//! verification: literal paths, renames, copies, binary counts and decline.
use serde_json::{json, Value};

pub(super) struct StructureDiff;

impl StructureDiff {
    pub(super) fn decode(payload: &Value) -> Option<Value> {
        let status = Self::name_status(payload.get("status")?.as_str()?)?;
        let counts = Self::numstat(payload.get("numstat")?.as_str()?)?;
        Some(json!({"status": status, "numstat": counts}))
    }

    fn name_status(text: &str) -> Option<Vec<(&str, &str, &str)>> {
        let mut fields = Self::fields(text)?;
        let mut records = Vec::new();
        while let Some(header) = fields.next() {
            let (code, score) = (header.get(..1)?, header.get(1..)?);
            if !matches!(code, "A" | "C" | "D" | "M" | "R" | "T" | "U" | "X" | "B")
                || !score.bytes().all(|digit| digit.is_ascii_digit())
            {
                return None;
            }
            let source = fields.next().filter(|path| !path.is_empty())?;
            let (destination, previous) = if matches!(code, "R" | "C") {
                (fields.next().filter(|path| !path.is_empty())?, source)
            } else {
                (source, "")
            };
            records.push((destination, code, previous));
        }
        Some(records)
    }

    fn numstat(text: &str) -> Option<Vec<(&str, u64, u64)>> {
        let mut fields = Self::fields(text)?;
        let mut records = Vec::new();
        while let Some(header) = fields.next() {
            let (added, rest) = header.split_once('\t')?;
            let (deleted, mut destination) = rest.split_once('\t')?;
            if destination.is_empty() {
                fields.next().filter(|path| !path.is_empty())?;
                destination = fields.next().filter(|path| !path.is_empty())?;
            }
            records.push((destination, Self::count(added)?, Self::count(deleted)?));
        }
        Some(records)
    }

    fn fields(text: &str) -> Option<impl Iterator<Item = &str>> {
        (text.is_empty() || text.ends_with('\0')).then(|| text.split_terminator('\0'))
    }

    fn count(value: &str) -> Option<u64> {
        if value == "-" {
            return Some(0);
        }
        if !value.bytes().all(|byte| byte.is_ascii_digit()) {
            return None;
        }
        value.parse().ok()
    }
}
