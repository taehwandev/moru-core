//! owner: read-only Figma handoff CLI dry-run ingress; allowed imports: source
//! guard, UTF-8 profile and pure plan renderer; forbidden imports: extraction,
//! credential lookup, network and filesystem writes; callers/tests: native alias
//! and offline dry-run fixtures; verification: argparse-compatible plan output.
use crate::{
    figma_process::FigmaProcess, pretool_guard::CallbackGuard, python_encoding::PythonEncoding,
    text::Text,
};
use serde_json::{json, Value};
use std::{
    ffi::OsString,
    io::{self, Write},
};

struct Plan {
    fields: Value,
    output: String,
    scale: f64,
    depth: i64,
    timeout: i64,
    max_assets: Option<i64>,
    dry: bool,
}

impl Plan {
    fn parse(args: &[OsString]) -> Option<Self> {
        let mut plan = Self {
            fields: json!({"url":null,"file_key":null,"node_id":null,"name":null,"images":true,"format":"png","export_assets":false}),
            output: String::new(),
            scale: 2.0,
            depth: 4,
            timeout: 60,
            max_assets: None,
            dry: false,
        };
        let mut args = args.iter();
        while let Some(raw) = args.next() {
            let raw = raw.to_str()?;
            match raw {
                "--dry-run" => plan.dry = true,
                "--no-images" => plan.fields["images"] = json!(false),
                "--export-assets" => plan.fields["export_assets"] = json!(true),
                "--include-image-fills" => {}
                _ => {
                    let (key, value) = if let Some(pair) = raw.split_once('=') {
                        pair
                    } else {
                        let next = args.next()?.to_str()?;
                        // argparse accepts negative integer and simple negative decimal
                        // tokens as values, but treats other leading dashes as options.
                        if next.starts_with('-') && !negative_argument(next) {
                            return None;
                        }
                        (raw, next)
                    };
                    plan.option(key, value)?;
                }
            }
        }
        plan.dry.then_some(plan)
    }

    fn option(&mut self, key: &str, value: &str) -> Option<()> {
        match key {
            "--url" | "--name" | "--file-key" | "--node-id" => {
                self.fields[key[2..].replace('-', "_")] = json!(value);
            }
            "--out" => self.output = value.to_owned(),
            "--token-env" => {}
            "--format" if matches!(value, "png" | "jpg" | "svg" | "pdf") => {
                self.fields["format"] = json!(value)
            }
            "--scale"
                if value
                    .bytes()
                    .all(|b| b.is_ascii_digit() || b".eE+-".contains(&b)) =>
            {
                self.scale = value.parse().ok()?
            }
            "--max-flow-depth" => self.depth = value.parse().ok()?,
            "--timeout" => self.timeout = value.parse().ok()?,
            "--max-assets" => self.max_assets = Some(value.parse().ok()?),
            _ => return None,
        }
        Some(())
    }

    fn receipt(mut self) -> Option<Value> {
        let error = if !(0.01..=4.0).contains(&self.scale) {
            Some("--scale must be between 0.01 and 4.0.")
        } else if self.timeout <= 0 {
            Some("--timeout must be greater than zero.")
        } else if self.depth < 0 {
            Some("--max-flow-depth must not be negative.")
        } else if self.max_assets.is_some_and(|v| v < 0) {
            Some("--max-assets must not be negative.")
        } else {
            None
        };
        if let Some(error) = error {
            return Some(json!({"error":error}));
        }
        let base = if self.output.is_empty() {
            std::env::current_dir()
                .ok()?
                .join(".figma-handoff-work")
                .to_str()?
                .to_owned()
        } else if self.output.starts_with('~') {
            return None;
        } else {
            Text::norm_path(&self.output)
        };
        self.fields["output_base"] = json!(base);
        self.fields["scale"] = json!(self.scale);
        self.fields["max_flow_depth"] = json!(self.depth);
        self.fields["timeout"] = json!(self.timeout);
        self.fields["max_assets"] = json!(self.max_assets);
        FigmaProcess::extractor_plan(&self.fields.to_string())
    }
}

fn negative_argument(value: &str) -> bool {
    let digits = |s: &str| !s.is_empty() && s.bytes().all(|b| b.is_ascii_digit());
    let Some(body) = value.strip_prefix('-') else {
        return false;
    };
    digits(body)
        || body
            .split_once('.')
            .is_some_and(|(a, b)| (a.is_empty() || digits(a)) && digits(b))
}

pub(crate) fn run(launcher: &OsString, args: &[OsString]) -> i32 {
    let Some(receipt) = Plan::parse(&args[1..]).and_then(|plan| {
        CallbackGuard::root(launcher, "git")?;
        PythonEncoding::utf8().then_some(())?;
        plan.receipt()
    }) else {
        crate::exec_python(launcher, args)
    };
    if let Some(message) = receipt["error"].as_str() {
        return if writeln!(io::stderr().lock(), "ERROR: {message}").is_ok() {
            2
        } else {
            1
        };
    }
    let Some(stdout) = receipt["stdout"].as_str() else {
        crate::exec_python(launcher, args)
    };
    i32::from(io::stdout().lock().write_all(stdout.as_bytes()).is_err())
}
