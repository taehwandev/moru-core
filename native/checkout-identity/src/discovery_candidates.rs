//! Owner: discovery name matching, ordered candidate merging and ranking.
//! Allowed: std, serde_json, discovery_fs, existing whitespace renderer.
//! Forbidden: registry reads, filesystem probes, effects, writes or caches.
//! Callers/tests: discovery_search/registry; native discovery/registry tests.
use crate::discovery_fs::DiscoveryFs as Fs;
use serde_json::{json, Value};
use std::{
    collections::BTreeMap,
    path::{Path, PathBuf},
};

pub(crate) struct Candidates(BTreeMap<PathBuf, Value>);

impl Candidates {
    pub(crate) fn new() -> Self {
        Self(BTreeMap::new())
    }

    pub(crate) fn add(
        &mut self,
        path: PathBuf,
        files: Vec<String>,
        markers: Vec<String>,
        base: i64,
        reason: &str,
        source: &str,
        aliases: &[String],
    ) -> Option<()> {
        let score = base
            + if files.is_empty() { 0 } else { 20 }
            + if markers.iter().any(|m| m == ".git") {
                10
            } else {
                0
            }
            + if markers.is_empty() { 0 } else { 5 };
        if let Some(existing) = self.0.get_mut(&path) {
            existing["confidence"] = json!(existing["confidence"].as_i64()?.max(score));
            for (key, incoming) in [
                ("reasons", vec![reason.to_owned()]),
                ("sources", vec![source.to_owned()]),
                ("instruction_files", files),
                ("markers", markers),
                ("aliases", aliases.to_vec()),
            ] {
                let mut joined = existing[key].as_array()?.clone();
                joined.extend(incoming.into_iter().map(Value::String));
                let mut unique = Vec::new();
                for item in joined {
                    if !unique.contains(&item) {
                        unique.push(item);
                    }
                }
                existing[key] = Value::Array(unique);
            }
        } else {
            self.0.insert(
                path.clone(),
                json!({"path":path.to_str()?,"confidence":score,"reasons":[reason],
                "instruction_files":files,"markers":markers,"sources":[source],"aliases":aliases}),
            );
        }
        Some(())
    }

    pub(crate) fn finish(self, request: &str) -> Option<Value> {
        let mut ranked: Vec<Value> = self.0.into_values().collect();
        for candidate in &mut ranked {
            let path = Path::new(candidate["path"].as_str()?);
            let mut matched = Self::matches(
                path.file_name().and_then(|s| s.to_str()).unwrap_or(""),
                request,
                false,
            )?;
            for alias in candidate["aliases"].as_array()? {
                if matched {
                    break;
                }
                matched = Self::matches(alias.as_str()?, request, true)?;
            }
            if matched {
                candidate["confidence"] = json!(candidate["confidence"].as_i64()? + 12);
                let reason = json!("candidate name appeared in request");
                let reasons = candidate["reasons"].as_array_mut()?;
                if !reasons.contains(&reason) {
                    reasons.push(reason);
                }
            }
        }
        ranked.sort_by(|a, b| {
            b["confidence"]
                .as_i64()
                .cmp(&a["confidence"].as_i64())
                .then_with(|| a["path"].as_str().cmp(&b["path"].as_str()))
        });
        let status = if ranked.is_empty() {
            "not_found"
        } else if ranked.len() == 1
            || ranked[0]["confidence"].as_i64()? - ranked[1]["confidence"].as_i64()? >= 20
        {
            "selected"
        } else {
            "ambiguous"
        };
        let selected = if status == "selected" {
            ranked[0].clone()
        } else {
            Value::Null
        };
        Some(json!({"status":status,"selected_project":selected,"candidates":ranked}))
    }

    pub(crate) fn has_slug(request: &str) -> bool {
        request.as_bytes().windows(3).any(|w| {
            w[0].is_ascii_alphanumeric()
                && matches!(w[1], b'-' | b'_')
                && w[2].is_ascii_alphanumeric()
        })
    }

    pub(crate) fn matches(name: &str, request: &str, generic: bool) -> Option<bool> {
        let name = Fs::lower(crate::statusline::Renderer::strip(name))?;
        let words = parts(&name);
        let normalized = words.join(" ");
        if name.is_empty()
            || (!generic
                && [
                    "app", "api", "backend", "client", "desktop", "frontend", "mobile", "server",
                    "web",
                ]
                .contains(&normalized.as_str()))
        {
            return Some(false);
        }
        for (start, _) in request.match_indices(&name) {
            let end = start + name.len();
            if (start == 0 || !boundary(request.as_bytes()[start - 1]))
                && (end == request.len() || !boundary(request.as_bytes()[end]))
            {
                return Some(true);
            }
        }
        Some(
            words.len() > 1
                && format!(" {} ", parts(request).join(" ")).contains(&format!(" {normalized} ")),
        )
    }
}

fn boundary(c: u8) -> bool {
    c.is_ascii_lowercase() || c.is_ascii_digit() || c == b'_' || c == b'-'
}
fn parts(value: &str) -> Vec<&str> {
    value
        .split(|c: char| !c.is_ascii_lowercase() && !c.is_ascii_digit())
        .filter(|v| !v.is_empty())
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn names_keep_slug_generic_and_alias_boundaries() {
        for (name, request, expected) in [
            ("moru-core", "moru core 수정", true),
            ("moru", "moru-core", false),
            ("web", "web", false),
            ("한글", "한글 수정", true),
            ("moru-core", "xmoru-core", false),
        ] {
            assert_eq!(Candidates::matches(name, request, false), Some(expected));
        }
        assert_eq!(Candidates::matches("web", "web", true), Some(true));
    }

    #[test]
    fn a_later_empty_alias_merge_also_deduplicates_existing_aliases() {
        let mut values = Candidates::new();
        let root = PathBuf::from("/synthetic/project");
        values
            .add(
                root.clone(),
                vec![],
                vec![],
                120,
                "registry",
                "registry",
                &["target".into(), "target".into()],
            )
            .unwrap();
        values
            .add(root, vec![], vec![], 65, "cwd", "cwd", &[])
            .unwrap();
        let result = values.finish("target").unwrap();
        assert_eq!(result["selected_project"]["aliases"], json!(["target"]));
        assert_eq!(
            result["selected_project"]["reasons"],
            json!(["registry", "cwd", "candidate name appeared in request"])
        );
    }
}
