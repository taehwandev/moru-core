//! owner: invoke the guarded Figma extractor once and inspect its scratch bundle;
//! allowed imports: scratch workspace, fixed subprocesses, offline Figma inspector;
//! forbidden imports: HTTP clients, persistent storage and extractor retries;
//! callers/tests: Figma live smoke alias and offline process fixtures;
//! verification: ordered output, receipt fallback and temporary directory cleanup.
use super::Options;
use crate::{
    figma_process::FigmaProcess, python_json::Number, smoke_workspace::SmokeWorkspace, text::Text,
};
use std::{
    env,
    io::{self, Write},
    path::Path,
    process::{Command, Stdio},
};

fn tail(bytes: &[u8], limit: usize) -> io::Result<String> {
    let text = std::str::from_utf8(bytes).map_err(io::Error::other)?;
    let normalized = Text::universal_newlines(text);
    let trimmed = Text::py_strip(&normalized);
    let start = trimmed
        .char_indices()
        .rev()
        .nth(limit.saturating_sub(1))
        .map_or(0, |(i, _)| i);
    Ok(trimmed[start..].to_owned())
}

fn inspect(
    root: &Path,
    bundle: &Path,
    options: &Options<'_>,
    scale: &str,
) -> io::Result<serde_json::Value> {
    if let Some(receipt) = FigmaProcess::inspect_smoke_bundle(bundle, options.quick, options.scale)
    {
        return Ok(receipt);
    }
    let result = Command::new("python3")
        .arg(root.join("scripts/figma-handoff/live_smoke.py"))
        .arg("--moru-inspect-bundle")
        .arg(bundle)
        .arg(if options.quick { "1" } else { "0" })
        .arg(scale)
        .stderr(Stdio::inherit())
        .output()?;
    if !result.status.success() {
        return Err(io::Error::other("bundle inspection failed"));
    }
    serde_json::from_slice(&result.stdout).map_err(io::Error::other)
}

fn extract(
    root: &Path,
    workspace: SmokeWorkspace,
    options: &Options<'_>,
    url: &str,
) -> io::Result<i32> {
    let scale = Number::float(options.scale);
    let mut command = Command::new("python3");
    command
        .arg(root.join("scripts/figma-handoff/figma-handoff.py"))
        .args(["--url", url, "--name", "smoke", "--out"])
        .arg(workspace.path())
        .args(["--scale", &scale, "--token-env", options.name]);
    if !options.quick {
        command.arg("--export-assets");
    }
    let result = command.stdin(Stdio::inherit()).output()?;
    let out = tail(&result.stdout, 600)?;
    let err = tail(&result.stderr, 800)?;
    writeln!(io::stdout().lock(), "{out}")?;
    if !result.status.success() {
        writeln!(io::stderr().lock(), "{err}")?;
        writeln!(io::stdout().lock(), "FAIL: tool exited non-zero")?;
        return Ok(1);
    }
    let receipt = inspect(root, &workspace.path().join("smoke"), options, &scale)?;
    let invalid = || io::Error::other("invalid bundle inspection receipt");
    let out = receipt["stdout"].as_str().ok_or_else(invalid)?;
    let after = receipt["after_cleanup"].as_str().ok_or_else(invalid)?;
    let code = receipt["code"]
        .as_i64()
        .filter(|v| matches!(v, 0 | 1))
        .ok_or_else(invalid)?;
    io::stdout().lock().write_all(out.as_bytes())?;
    drop(workspace);
    io::stdout().lock().write_all(after.as_bytes())?;
    Ok(code as i32)
}

pub(super) fn run(root: &Path, options: &Options<'_>, url: &str) -> Option<i32> {
    let temp = ["TMPDIR", "TEMP", "TMP"]
        .iter()
        .filter_map(env::var_os)
        .find(|p| !p.is_empty())
        .map(std::path::PathBuf::from)
        .unwrap_or_else(|| "/tmp".into());
    let workspace = SmokeWorkspace::figma(&temp.canonicalize().ok()?).ok()?;
    // Allocation commits this invocation. Errors below never replay extraction.
    Some(
        extract(root, workspace, options, url).unwrap_or_else(|error| {
            let _ = writeln!(io::stderr().lock(), "figma-live-smoke: {error}");
            1
        }),
    )
}
