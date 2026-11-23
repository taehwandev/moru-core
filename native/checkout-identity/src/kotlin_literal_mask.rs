//! owner: Kotlin literal and comment masking for Compose diagnostics.
//! allowed imports: Compose aliases, ranges and receivers, JSON and standard-library collections.
//! forbidden imports: source IO, Git execution, mutation and approval.
//! callers/tests: Compose action scan through the private completion probe.
//! verification: exact Python mask and diagnostic offset parity.
use super::{
    kotlin_compose_aliases::KotlinComposeAliases, kotlin_compose_bodies::KotlinComposeBodies,
    kotlin_compose_callbacks::KotlinComposeCallbacks,
    kotlin_compose_viewmodels::KotlinComposeViewModels,
};
use serde_json::{json, Value};
use std::borrow::Cow;
use std::collections::HashSet;

pub(super) struct KotlinLiteralMask;

impl KotlinLiteralMask {
    pub(super) fn mask(input: &Value) -> Option<Value> {
        let source = input.get("source")?.as_str()?;
        // Python indexes Unicode code points, so blank each scalar with one space.
        let mut code = source.chars().collect::<Vec<_>>();
        let mut start = 0;
        while start < code.len() {
            let rest = &code[start..];
            let end = match rest {
                ['/', '/', ..] => rest.iter().position(|&ch| ch == '\n').unwrap_or(rest.len()),
                ['/', '*', ..] => Self::comment_end(rest),
                ['"', '"', '"', ..] => rest[3..]
                    .windows(3)
                    .position(|window| window == ['"', '"', '"'])
                    .map_or(rest.len(), |offset| offset + 6),
                [quote @ ('"' | '\''), ..] => Self::quoted_end(rest, *quote),
                _ => {
                    start += 1;
                    continue;
                }
            };
            for ch in &mut code[start..start + end] {
                if *ch != '\n' {
                    *ch = ' ';
                }
            }
            start += end;
        }
        let masked: String = code.iter().collect();
        let version = input.get("unicode").and_then(Value::as_str);
        let normalized = version
            .filter(|_| input.get("normalize_aliases").and_then(Value::as_bool) == Some(true))
            .and_then(|version| KotlinComposeAliases::normalize(&masked, version));
        let normalized_chars = match &normalized {
            Some(Cow::Owned(text)) => Some(text.chars().collect::<Vec<_>>()),
            _ => None,
        };
        let prepared = normalized_chars.as_deref().unwrap_or(&code);
        let bodies = version.and_then(|version| KotlinComposeBodies::ranges(prepared, version));
        let mut result = json!({"code": masked});
        if let Some(normalized) = normalized {
            result["aliases_normalized"] = json!(true);
            if let Cow::Owned(text) = normalized {
                result["normalized_code"] = json!(text);
            }
        }
        if let Some(bodies) = bodies {
            Self::add_scopes(input, &mut result, prepared, &bodies);
            result["bodies"] = json!(bodies);
        }
        Some(result)
    }

    fn add_scopes(input: &Value, result: &mut Value, code: &[char], bodies: &[[usize; 3]]) {
        let callbacks = input.get("callback_scopes").and_then(Value::as_bool) == Some(true);
        let viewmodels = input.get("viewmodel_scopes").and_then(Value::as_bool) == Some(true);
        if !callbacks && !viewmodels {
            return;
        }
        let mut callback_scopes = Vec::new();
        let mut viewmodel_scopes = Vec::new();
        for &[signature, start, end] in bodies {
            let names = viewmodels.then(|| KotlinComposeViewModels::names(&code[signature..start]));
            let receivers = names
                .as_ref()
                .map(|names| names.iter().copied().collect::<HashSet<_>>());
            let [events, hosts, collectors] =
                KotlinComposeCallbacks::regions(&code[start..end], receivers.as_ref());
            if callbacks {
                callback_scopes.push([events, hosts]);
            }
            if let Some(names) = names {
                let names: Vec<String> = names.iter().map(|name| name.iter().collect()).collect();
                viewmodel_scopes.push(json!({"names": names, "collectors": collectors}));
            }
        }
        if callbacks {
            result["callback_scopes"] = json!(callback_scopes);
        }
        if viewmodels {
            result["viewmodel_scopes"] = json!(viewmodel_scopes);
        }
    }

    fn comment_end(code: &[char]) -> usize {
        let mut index = 2;
        let mut depth = 1;
        while index < code.len() && depth != 0 {
            match &code[index..] {
                ['/', '*', ..] => {
                    depth += 1;
                    index += 2;
                }
                ['*', '/', ..] => {
                    depth -= 1;
                    index += 2;
                }
                _ => index += 1,
            }
        }
        index
    }

    fn quoted_end(code: &[char], quote: char) -> usize {
        let mut index = 1;
        while index < code.len() {
            match code[index] {
                '\\' => index += 2,
                ch if ch == quote => return index + 1,
                _ => index += 1,
            }
        }
        index.min(code.len())
    }
}
