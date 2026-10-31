use serde_json::{Map, Value};

use super::gauge::Gauge;
use super::py::Py;

const USED_KEYS: [&str; 4] = ["used_percentage", "used_percent", "percent", "utilization"];
const LABELS: [&str; 2] = ["5h", "7d"];

pub(crate) struct Quota;

impl Quota {
    /// None means an unsupported shape was met and Python must decide.
    pub(crate) fn render(root: &Map<String, Value>, color: bool) -> Option<String> {
        let mut entries: Vec<(String, &Map<String, Value>)> = Vec::new();
        match root.get("rate_limits") {
            Some(Value::Object(limits)) => {
                for (key, value) in limits {
                    if let Value::Object(entry) = value {
                        entries.push((key.clone(), entry));
                    }
                }
            }
            Some(Value::Array(items)) => {
                for item in items {
                    if let Value::Object(entry) = item {
                        let key = match Py::pick(entry, &["kind", "window"]) {
                            None => String::new(),
                            Some(Value::String(key)) => key.clone(),
                            Some(_) => return None,
                        };
                        entries.push((key, entry));
                    }
                }
            }
            _ => {}
        }

        let mut slots: [Option<f64>; 2] = [None, None];
        for (key, entry) in entries {
            let Some(used) = Self::used(entry)? else {
                continue;
            };
            if let Some(slot) = Self::slot(&key, entry)? {
                slots[slot] = Some(used);
            }
        }

        let segments: Vec<String> = slots
            .iter()
            .zip(LABELS)
            .filter_map(|(used, label)| used.map(|used| Self::segment(label, used, color)))
            .collect();
        Some(segments.join(" · "))
    }

    fn segment(label: &str, used: f64, color: bool) -> String {
        let remaining = (100.0 - used).round_ties_even().clamp(0.0, 100.0) as u32;
        let mark = if remaining <= 15 { "!" } else { "" };
        let text = format!("{mark}{label} {} {remaining:>3}%", Gauge::render(remaining));
        if !color {
            return text;
        }
        let open = if remaining <= 15 {
            "\x1b[1m\x1b[31m"
        } else if remaining <= 40 {
            "\x1b[33m"
        } else {
            "\x1b[36m"
        };
        format!("{open}{text}\x1b[0m")
    }

    fn slot(key: &str, entry: &Map<String, Value>) -> Option<Option<usize>> {
        let window = match entry.get("window_minutes") {
            Some(Value::Number(value)) => value.as_f64(),
            Some(Value::String(value)) => Self::parse(value).ok()?,
            _ => None,
        }
        .filter(|minutes| *minutes > 0.0);
        if let Some(minutes) = window {
            let rounded = minutes.round_ties_even();
            return Some(if rounded == 300.0 {
                Some(0)
            } else if rounded == 10080.0 {
                Some(1)
            } else {
                None
            });
        }
        let key = key.to_lowercase();
        Some(
            if key.contains("five_hour")
                || key.contains("5_hour")
                || key == "session"
                || key == "primary"
            {
                Some(0)
            } else if key.contains("seven_day")
                || key.contains("7_day")
                || key.contains("week")
                || key == "secondary"
            {
                Some(1)
            } else {
                None
            },
        )
    }

    /// Outer None: unsupported, use Python. Inner None: no convertible value.
    fn used(entry: &Map<String, Value>) -> Option<Option<f64>> {
        for name in USED_KEYS {
            match entry.get(name) {
                Some(Value::Number(number)) => return number.as_f64().map(Some),
                Some(Value::String(text)) => match Self::parse(text) {
                    Ok(Some(value)) => return Some(Some(value)),
                    Ok(None) => {}
                    Err(()) => return None,
                },
                _ => {}
            }
        }
        Some(None)
    }

    /// Ok(Some) value, Ok(None) ordinary invalid text, Err unsupported spelling.
    fn parse(text: &str) -> Result<Option<f64>, ()> {
        let text = Py::strip(text);
        if Self::safe(text) {
            return match text.parse::<f64>() {
                Ok(value) if value.is_finite() => Ok(Some(value)),
                _ => Err(()),
            };
        }
        let lower = text.to_ascii_lowercase();
        let bare = lower.trim_start_matches(['+', '-']);
        if !text.is_ascii()
            || text.contains('_')
            || bare.starts_with("inf")
            || bare.starts_with("nan")
        {
            Err(())
        } else {
            Ok(None)
        }
    }

    fn safe(text: &str) -> bool {
        let bytes = text.as_bytes();
        let digits = |at: &mut usize| {
            let start = *at;
            while *at < bytes.len() && bytes[*at].is_ascii_digit() {
                *at += 1;
            }
            *at - start
        };
        let mut at = 0;
        if matches!(bytes.first(), Some(b'+' | b'-')) {
            at += 1;
        }
        let mut count = digits(&mut at);
        if bytes.get(at) == Some(&b'.') {
            at += 1;
            count += digits(&mut at);
        }
        if count == 0 {
            return false;
        }
        if matches!(bytes.get(at), Some(b'e' | b'E')) {
            at += 1;
            if matches!(bytes.get(at), Some(b'+' | b'-')) {
                at += 1;
            }
            if digits(&mut at) == 0 {
                return false;
            }
        }
        at == bytes.len()
    }
}
