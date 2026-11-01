//! Owner: generated project-discover CLI adapter and exact output rendering.
//! Allowed: std, serde_json, existing source guard and discovery_search.
//! Forbidden: state writes, process discovery, authority changes or caches.
//! Callers/tests: launcher_main; test_native_project_discovery, bundle smoke.
use crate::{discovery_search::DiscoverySearch, pretool_guard::CallbackGuard};
use serde_json::{Map, Value};
use std::{
    env,
    ffi::OsString,
    io::{Read, Write},
    path::PathBuf,
};

pub(crate) struct DiscoveryProcess;

impl DiscoveryProcess {
    pub(crate) fn run(launcher: &OsString, args: &[OsString]) -> i32 {
        let probe = args.get(1).is_some_and(|v| v == "--native-probe");
        let words = if probe { &args[2..] } else { &args[1..] };
        let Some((result, format)) = discover(launcher, words, probe) else {
            if probe {
                return 125;
            }
            // The replaying Python CLI must not spawn another private probe
            // for the input/source/environment this process already declined.
            env::set_var("MORU_DISCOVERY_NATIVE_DECLINED", "1");
            crate::exec_python(launcher, args);
        };
        let code = match result["status"].as_str() {
            Some("selected") => 0,
            Some("ambiguous") => 2,
            _ => 3,
        };
        let output = if format == "json" {
            ascii_json(result)
        } else {
            render(&result)
        };
        match std::io::stdout().write_all(output.as_bytes()) {
            Ok(()) => code,
            Err(_) => 1,
        }
    }
}

fn discover(launcher: &OsString, args: &[OsString], probe: bool) -> Option<(Value, String)> {
    let mut request = None;
    let mut cwd = env::current_dir().ok()?;
    let mut registry = None;
    let mut roots = Vec::new();
    let mut depth = 2;
    let mut defaults = false;
    let mut no_defaults = false;
    let mut format = "text".to_owned();
    let mut registry_stdin = false;
    let mut words = args.iter();
    while let Some(word) = words.next() {
        match word.to_str()? {
            "--request" if request.is_none() => request = Some(words.next()?.to_str()?.to_owned()),
            "--cwd" => cwd = PathBuf::from(words.next()?),
            "--registry" => registry = Some(PathBuf::from(words.next()?)),
            "--search-root" => roots.push(PathBuf::from(words.next()?)),
            "--max-depth" => depth = words.next()?.to_str()?.parse::<i32>().ok()?.max(0) as usize,
            "--include-default-search-roots" => defaults = true,
            "--no-default-search-roots" => no_defaults = true,
            "--registry-stdin" if probe => registry_stdin = true,
            "--format" => {
                format = words.next()?.to_str()?.to_owned();
                if !["text", "json"].contains(&format.as_str()) {
                    return None;
                }
            }
            _ => return None,
        }
    }
    let request = request?;
    CallbackGuard::root(launcher, "project-discover")?;
    let snapshot = if registry_stdin {
        let mut bytes = Vec::new();
        std::io::stdin()
            .take(1024 * 1024 + 1)
            .read_to_end(&mut bytes)
            .ok()?;
        if bytes.len() > 1024 * 1024 {
            return None;
        }
        Some(serde_json::from_slice(&bytes).ok()?)
    } else {
        None
    };
    Some((
        DiscoverySearch::find(
            &request,
            &cwd,
            registry.as_deref(),
            &roots,
            depth,
            defaults && !no_defaults,
            snapshot.as_ref(),
        )?,
        format,
    ))
}

fn ordered(value: Value) -> Value {
    match value {
        Value::Object(map) => {
            let mut pairs: Vec<_> = map.into_iter().collect();
            pairs.sort_by(|a, b| a.0.cmp(&b.0));
            Value::Object(
                pairs
                    .into_iter()
                    .map(|(k, v)| (k, ordered(v)))
                    .collect::<Map<_, _>>(),
            )
        }
        Value::Array(items) => Value::Array(items.into_iter().map(ordered).collect()),
        other => other,
    }
}

fn ascii_json(value: Value) -> String {
    let mut output = String::new();
    for c in serde_json::to_string_pretty(&ordered(value))
        .unwrap()
        .chars()
    {
        if c.is_ascii() {
            output.push(c);
        } else {
            for word in c.encode_utf16(&mut [0; 2]) {
                output.push_str(&format!("\\u{word:04x}"));
            }
        }
    }
    output.push('\n');
    output
}

fn render(result: &Value) -> String {
    let mut lines = vec![format!("status: {}", result["status"].as_str().unwrap())];
    let selected = &result["selected_project"];
    if selected.is_object() {
        lines.push(format!("project: {}", selected["path"].as_str().unwrap()));
        let files = selected["instruction_files"].as_array().unwrap();
        if !files.is_empty() {
            lines.push("instruction_files:".into());
            lines.extend(files.iter().map(|f| format!("- {}", f.as_str().unwrap())));
        }
    } else {
        let candidates = result["candidates"].as_array().unwrap();
        if !candidates.is_empty() {
            lines.push("candidates:".into());
        }
        for candidate in candidates {
            lines.push(format!(
                "- {} ({})",
                candidate["path"].as_str().unwrap(),
                candidate["confidence"]
            ));
            for (key, label) in [
                ("reasons", "reason"),
                ("instruction_files", "instruction_files"),
            ] {
                let items: Vec<_> = candidate[key]
                    .as_array()
                    .unwrap()
                    .iter()
                    .map(|i| i.as_str().unwrap())
                    .collect();
                if !items.is_empty() {
                    lines.push(format!("  {label}: {}", items.join(", ")));
                }
            }
        }
    }
    lines.join("\n") + "\n"
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn json_retains_python_ascii_and_sorted_keys() {
        assert_eq!(
            ascii_json(serde_json::json!({"z":"한😀","a":[]})),
            "{\n  \"a\": [],\n  \"z\": \"\\ud55c\\ud83d\\ude00\"\n}\n"
        );
    }
}
