//! owner: ManifestValidation; allowed imports: std, serde_json; forbidden imports:
//! process/network; callers/tests: ReactManifest; verification: manifest parity.
use serde_json::{Map, Value};
use std::collections::BTreeSet;
use std::path::{Component, Path};
pub struct ManifestValidation;
impl ManifestValidation {
    pub fn truthy(v: &Value) -> bool {
        match v {
            Value::Null => false,
            Value::Bool(v) => *v,
            Value::Number(v) => v.as_f64() != Some(0.0),
            Value::String(v) => !v.is_empty(),
            Value::Array(v) => !v.is_empty(),
            Value::Object(v) => !v.is_empty(),
        }
    }
    pub fn string(v: &Value) -> Option<String> {
        Some(match v {
            Value::Null => "None".into(),
            Value::Bool(v) => if *v { "True" } else { "False" }.into(),
            Value::String(v) => v.clone(),
            Value::Number(v) if v.is_i64() || v.is_u64() => v.to_string(),
            Value::Number(v) => Self::float(v.as_f64()?),
            Value::Array(v) => format!(
                "[{}]",
                v.iter()
                    .map(Self::repr)
                    .collect::<Option<Vec<_>>>()?
                    .join(", ")
            ),
            Value::Object(v) => format!(
                "{{{}}}",
                v.iter()
                    .map(|(k, v)| Some(format!(
                        "{}: {}",
                        Self::repr(&Value::String(k.clone()))?,
                        Self::repr(v)?
                    )))
                    .collect::<Option<Vec<_>>>()?
                    .join(", ")
            ),
        })
    }
    fn float(v: f64) -> String {
        // Rust and Python use shortest round-trip digits, with different exponent spelling.
        let raw = format!("{v:?}");
        let Some((mantissa, exponent)) = raw.split_once('e') else {
            return raw;
        };
        let exponent: i32 = exponent.parse().expect("Rust float exponent");
        if !(-4..16).contains(&exponent) {
            return format!(
                "{}e{}{:02}",
                mantissa,
                if exponent >= 0 { "+" } else { "-" },
                exponent.abs()
            );
        }
        let sign = if mantissa.starts_with('-') { "-" } else { "" };
        let digits = mantissa.trim_start_matches('-').replace('.', "");
        let point = 1 + exponent;
        if point <= 0 {
            format!("{sign}0.{}{digits}", "0".repeat((-point) as usize))
        } else if point as usize >= digits.len() {
            format!(
                "{sign}{digits}{}.0",
                "0".repeat(point as usize - digits.len())
            )
        } else {
            format!(
                "{sign}{}.{}",
                &digits[..point as usize],
                &digits[point as usize..]
            )
        }
    }
    fn repr(v: &Value) -> Option<String> {
        if let Value::String(s) = v {
            if !s.is_ascii() {
                return None;
            }
            let quote = if s.contains('\'') && !s.contains('"') {
                '"'
            } else {
                '\''
            };
            let mut out = String::from(quote);
            for c in s.chars() {
                match c {
                    '\\' => out.push_str("\\\\"),
                    '\n' => out.push_str("\\n"),
                    '\r' => out.push_str("\\r"),
                    '\t' => out.push_str("\\t"),
                    c if c == quote => {
                        out.push('\\');
                        out.push(c);
                    }
                    c if c.is_ascii_control() => out.push_str(&format!("\\x{:02x}", c as u32)),
                    c => out.push(c),
                }
            }
            out.push(quote);
            Some(out)
        } else {
            Self::string(v)
        }
    }
    pub fn field(m: &Map<String, Value>, key: &str) -> Option<String> {
        m.get(key)
            .map(Self::string)
            .unwrap_or_else(|| Some(String::new()))
    }
    pub fn sha(s: &str, n: usize) -> bool {
        s.len() == n
            && s.bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    }
    fn blank(s: &str) -> bool {
        s.chars()
            .all(|c| c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c))
    }
    fn equals(v: Option<&Value>, n: u64) -> bool {
        match v {
            Some(Value::Bool(b)) => u64::from(*b) == n,
            Some(Value::Number(v)) => v.as_f64() == Some(n as f64),
            _ => false,
        }
    }
    pub fn failures(payload: &Value, root: &Path) -> Option<Vec<String>> {
        let p = payload.as_object()?;
        let empty = Map::new();
        let no_entries = Vec::new();
        let entries = match p.get("skills") {
            None => &no_entries,
            Some(v) => match v.as_array() {
                Some(v) => v,
                None => return Some(vec![Self::schema()]),
            },
        };
        let snapshot = match p.get("snapshot") {
            None => &empty,
            Some(v) => match v.as_object() {
                Some(v) => v,
                None => return Some(vec![Self::schema()]),
            },
        };
        let repos = match p.get("repositories") {
            None => &empty,
            Some(v) => match v.as_object() {
                Some(v) => v,
                None => return Some(vec![Self::schema()]),
            },
        };
        if !Self::equals(p.get("schema_version"), 1) {
            return Some(vec![Self::schema()]);
        }
        let mut f = Vec::new();
        for (provider, record) in repos {
            let Some(r) = record.as_object() else {
                f.push(format!(
                    "repository {provider} must be an object with url, commit, and provenance"
                ));
                continue;
            };
            if !Self::field(r, "url")?.starts_with("https://") {
                f.push(format!("repository {provider} needs an https url"));
            }
            let commit = Self::field(r, "commit")?;
            let provenance = Self::field(r, "provenance")?;
            match provenance.as_str() {
                "unpinned" if commit != "unknown" => f.push(format!(
                    "repository {provider} is unpinned and must record commit unknown"
                )),
                "content_verified" if !Self::sha(&commit, 40) => f.push(format!(
                    "repository {provider} must pin a full 40-character commit sha"
                )),
                "unpinned" | "content_verified" => {}
                _ => f.push(format!(
                    "repository {provider} provenance must be content_verified or unpinned"
                )),
            }
            if Self::blank(&Self::field(r, "verified_at")?) {
                f.push(format!("repository {provider} needs a verified_at date"));
            }
        }
        let paths = entries
            .iter()
            .filter_map(Value::as_object)
            .map(|e| Self::field(e, "path"))
            .collect::<Option<Vec<_>>>()?;
        if entries.len() != 41 || paths.iter().collect::<BTreeSet<_>>().len() != paths.len() {
            f.push("manifest must contain 41 unique SKILL.md paths".into());
        }
        if paths.windows(2).any(|p| p[0] > p[1]) {
            f.push("manifest SKILL.md paths must stay sorted".into());
        }
        let installable = entries
            .iter()
            .filter_map(Value::as_object)
            .filter(|e| e.get("installable").is_some_and(Self::truthy))
            .count();
        if installable != 32 {
            f.push("manifest must identify exactly 32 installable skills".into());
        }
        let expected = [
            ("vercel", 4),
            ("expo", 20),
            ("callstack", 7),
            ("software_mansion", 1),
        ];
        if repos.len() != 4
            || expected.iter().any(|(name, count)| {
                !repos.contains_key(*name)
                    || entries
                        .iter()
                        .filter_map(Value::as_object)
                        .filter(|e| {
                            e.get("installable").is_some_and(Self::truthy)
                                && e.get("provider").and_then(Value::as_str) == Some(*name)
                        })
                        .count()
                        != *count
            })
        {
            f.push("installable provider counts must remain Vercel 4, Expo 20, Callstack 7, Software Mansion 1".into());
        }
        if [
            ("installable_skills", 32),
            ("nested_skills", 9),
            ("skill_files", 41),
        ]
        .iter()
        .any(|(k, n)| !Self::equals(snapshot.get(*k), *n))
        {
            f.push("snapshot counts must declare 32 installable, 9 nested, and 41 total".into());
        }
        for entry in entries {
            let Some(e) = entry.as_object() else {
                f.push("every skill entry must be an object".into());
                continue;
            };
            let path = Self::field(e, "path")?;
            if !path.ends_with("/SKILL.md")
                || Path::new(&path).is_absolute()
                || Path::new(&path)
                    .components()
                    .any(|c| c == Component::ParentDir)
            {
                f.push(format!(
                    "invalid skill path: {}",
                    if path.is_empty() { "<empty>" } else { &path }
                ));
            }
            if ["disposition", "provider"]
                .iter()
                .any(|k| e.get(*k).is_some_and(|v| v.is_array() || v.is_object()))
            {
                return None;
            }
            if !matches!(
                e.get("disposition").and_then(Value::as_str),
                Some("distilled" | "source_only")
            ) {
                f.push(format!("invalid disposition for {path}"));
            }
            if !e
                .get("provider")
                .and_then(Value::as_str)
                .is_some_and(|p| repos.contains_key(p))
            {
                f.push(format!("unknown provider for {path}"));
            }
            if Self::blank(&Self::field(e, "surface")?) {
                f.push(format!("missing surface for {path}"));
            }
            if !Self::sha(&Self::field(e, "sha256")?, 64) {
                f.push(format!("invalid sha256 for {path}"));
            }
            match e.get("owners").and_then(Value::as_array) {
                Some(owners) if !owners.is_empty() => {
                    for owner in owners {
                        let owner = Self::string(owner)?;
                        if !root.join(&owner).is_file() {
                            f.push(format!("missing owner for {path}: {owner}"));
                        }
                    }
                }
                _ => f.push(format!("missing owners for {path}")),
            }
        }
        Some(f)
    }
    fn schema() -> String {
        "manifest must use schema_version 1 with snapshot, repositories, and skills".into()
    }
}
#[cfg(test)]
#[path = "react_manifest_validation_tests.rs"]
mod tests;
