//! owner: read-only decision CLI argument admission.
//! allowed imports: bounded JSON, numeric parsing and lexical paths.
//! forbidden imports: file content, credentials, provider calls and report writes.
//! callers/tests: DecisionCachePlan and decision CLI parity fixtures.
//! verification: unique abbreviations, repeated options and compatibility declines.
use serde_json::Value;
use std::path::{self, PathBuf};

const OPTIONS: [&str; 8] = [
    "--input",
    "--cache-dir",
    "--model",
    "--max-calls",
    "--ttl-hours",
    "--refresh",
    "--execute",
    "--help",
];

pub(crate) struct DecisionCli {
    pub(crate) input: PathBuf,
    pub(crate) cache_dir: PathBuf,
    pub(crate) model: String,
    pub(crate) ttl: f64,
    pub(crate) refresh: bool,
}

impl DecisionCli {
    pub(crate) fn parse(request: &Value) -> Option<Self> {
        let models = request.get("models")?.as_array()?;
        let mut model = models.first()?.as_str()?;
        let mut input = None;
        let mut cache_dir = ".moru/research-cache/ms";
        let mut ttl_hours: f64 = 24.0;
        let mut max_calls: i64 = 10;
        let mut refresh = false;
        let mut argv = request.get("argv")?.as_array()?.iter();
        while let Some(arg) = argv.next() {
            let arg = arg.as_str()?;
            let (key, explicit) = arg
                .split_once('=')
                .map_or((arg, None), |(k, v)| (k, Some(v)));
            let name = option(key)?;
            match name {
                "--execute" | "--help" => return None,
                "--refresh" if explicit.is_none() => {
                    refresh = true;
                    continue;
                }
                "--refresh" => return None,
                _ => {}
            }
            let value = match explicit {
                Some(value) => value,
                None => {
                    let value = argv.next()?.as_str()?;
                    if value.starts_with('-') && value != "-" {
                        return None;
                    }
                    value
                }
            };
            match name {
                "--input" => input = Some(value),
                "--cache-dir" => cache_dir = value,
                "--model"
                    if models
                        .iter()
                        .any(|candidate| candidate.as_str() == Some(value)) =>
                {
                    model = value;
                }
                "--max-calls" => max_calls = value.trim_ascii().parse().ok()?,
                "--ttl-hours" => ttl_hours = value.trim_ascii().parse().ok()?,
                _ => return None,
            }
        }
        let ttl = ttl_hours * 3600.0;
        if max_calls < 0 || !ttl.is_finite() || ttl <= 0.0 {
            return None;
        }
        Some(Self {
            input: path::absolute(input?).ok()?,
            cache_dir: path::absolute(cache_dir).ok()?,
            model: model.into(),
            ttl,
            refresh,
        })
    }
}

fn option(key: &str) -> Option<&'static str> {
    if !key.starts_with("--") || key == "--" {
        return None;
    }
    let mut matches = OPTIONS.into_iter().filter(|name| name.starts_with(key));
    let name = matches.next()?;
    matches.next().is_none().then_some(name)
}
