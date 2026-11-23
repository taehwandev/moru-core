//! owner: Kotlin literal and comment masking for Compose diagnostics.
//! allowed imports: Compose body ranges, JSON and standard-library string operations.
//! forbidden imports: source IO, Git execution, mutation and approval.
//! callers/tests: Compose action scan through the private completion probe.
//! verification: exact Python mask and diagnostic offset parity.
use super::kotlin_compose_bodies::KotlinComposeBodies;
use serde_json::{json, Value};

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
        let bodies = input
            .get("unicode")
            .and_then(Value::as_str)
            .and_then(|version| KotlinComposeBodies::ranges(&code, version));
        let mut result = json!({"code": code.into_iter().collect::<String>()});
        if let Some(bodies) = bodies {
            result["bodies"] = json!(bodies);
        }
        Some(result)
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
