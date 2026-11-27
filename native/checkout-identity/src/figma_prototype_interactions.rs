//! Owner: offline prototype interaction projection.
//! Allowed imports: ordered JSON and Figma node IDs. Forbidden: I/O and provider access.
//! Callers/tests: Figma process probe and bound prototype extraction fixtures.
use super::target::Target;
use crate::python_json::{Number, Object, PythonJson, Value};
use serde_json::json;

fn object<const N: usize>(fields: [(&str, Value); N]) -> Value {
    let mut object = Object::new();
    for (key, value) in fields {
        object.insert(key.into(), value);
    }
    Value::Object(object)
}

fn optional_id(value: &Value) -> Option<Value> {
    match value.as_str().filter(|id| !id.is_empty()) {
        Some(id) => Some(Value::String(Target::normalize(id)?)),
        None => Some(Value::Null),
    }
}

fn round_number(value: f64) -> Number {
    let integer = value.round_ties_even();
    if (value - integer).abs() < 0.001 {
        return Number::Integer((integer as i64).to_string());
    }
    // Formatting the actual binary float avoids rounding an intermediate
    // scaled float, which changes outcomes at decimal half-cent boundaries.
    Number::Float(format!("{value:.2}").parse().expect("finite decimal"))
}

fn duration(value: &Value) -> Option<Value> {
    let number = match value {
        Value::Number(Number::Integer(value)) => value.parse::<f64>().ok()?,
        Value::Number(Number::Float(value)) => *value,
        _ => return Some(Value::Null),
    };
    if !number.is_finite() || number.abs() >= 9_007_199_254_740_992.0 {
        return None;
    }
    let rounded = round_number(number);
    let numeric = match &rounded {
        Number::Integer(text) => text.parse::<f64>().ok()?,
        Number::Float(value) => *value,
    };
    Some(Value::Number(if numeric > 10.0 {
        round_number(numeric / 1000.0)
    } else {
        rounded
    }))
}

fn legacy_source(target: &Value) -> Value {
    if PythonJson::truthy(target) {
        Value::String("transitionNodeID".into())
    } else {
        Value::Null
    }
}

struct Node {
    id: String,
    name: String,
    target: Value,
    transition: Value,
}

impl Node {
    fn fallback(&self, trigger: &Value, legacy_only: bool) -> Value {
        let action_type = if legacy_only {
            Value::String("NODE".into())
        } else {
            Value::Null
        };
        object([
            ("fromNodeId", Value::String(self.id.clone())),
            ("fromName", Value::String(self.name.clone())),
            ("triggerType", trigger["type"].clone()),
            ("actionType", action_type),
            ("navigation", Value::Null),
            ("toNodeId", self.target.clone()),
            ("destinationSource", legacy_source(&self.target)),
            ("transition", self.transition.clone()),
            ("rawTrigger", trigger.clone()),
            ("rawAction", Value::Null),
        ])
    }

    fn action(&self, trigger: &Value, action: &Value) -> Option<Value> {
        let mut target = Value::Null;
        let mut source = Value::Null;
        for key in ["destinationId", "destinationID", "destinationNodeID"] {
            if PythonJson::truthy(&action[key]) {
                target = optional_id(&action[key])?;
                if PythonJson::truthy(&target) {
                    source = Value::String(format!("action.{key}"));
                }
                break;
            }
        }
        if matches!(target, Value::Null) && PythonJson::truthy(&self.target) {
            target = self.target.clone();
            source = legacy_source(&target);
        }
        let transition = &action["transition"];
        let easing = &transition["easing"];
        let easing_type = if PythonJson::truthy(&easing["type"]) {
            &easing["type"]
        } else {
            easing
        };
        Some(object([
            ("fromNodeId", Value::String(self.id.clone())),
            ("fromName", Value::String(self.name.clone())),
            ("triggerType", trigger["type"].clone()),
            ("actionType", action["type"].clone()),
            ("navigation", action["navigation"].clone()),
            ("toNodeId", target),
            ("destinationSource", source),
            (
                "transition",
                object([
                    ("type", transition["type"].clone()),
                    ("durationSeconds", duration(&transition["duration"])?),
                    ("easingType", easing_type.clone()),
                    ("direction", transition["direction"].clone()),
                    ("matchLayers", transition["matchLayers"].clone()),
                    (
                        "easingFunctionCubicBezier",
                        transition["easingFunctionCubicBezier"].clone(),
                    ),
                ]),
            ),
            ("rawTrigger", trigger.clone()),
            ("rawAction", action.clone()),
        ]))
    }
}

fn append(output: &mut String, row: Value) -> Option<()> {
    let row = PythonJson::render(&row, false, true)?;
    // Bound the amplified output when an interaction repeats its trigger for
    // many actions. The existing transport applies its own envelope limit.
    if output.len() + row.len() > 1024 * 1024 {
        return None;
    }
    if output.len() > 1 {
        output.push(',');
    }
    output.push_str(&row);
    Some(())
}

pub(super) fn summarize(text: &str) -> Option<serde_json::Value> {
    let input = PythonJson::parse(text)?;
    let mut output = String::from("[");
    for row in input.as_array()? {
        row.as_object()?;
        let id = row.get("id").map(PythonJson::string).unwrap_or_default();
        let id = Target::normalize(&id)?;
        if id.is_empty() {
            continue;
        }
        let node = Node {
            id,
            name: row.get("name").map(PythonJson::string).unwrap_or_default(),
            target: optional_id(&row["transitionNodeID"])?,
            transition: object([
                ("type", Value::Null),
                ("durationSeconds", duration(&row["transitionDuration"])?),
                ("easingType", row["transitionEasing"].clone()),
            ]),
        };
        if let Some(interactions) = row["interactions"]
            .as_array()
            .filter(|rows| !rows.is_empty())
        {
            for interaction in interactions.iter().filter(|item| item.is_object()) {
                let empty = Value::Object(Object::new());
                let trigger = interaction
                    .get("trigger")
                    .filter(|item| item.is_object())
                    .unwrap_or(&empty);
                if let Some(actions) = interaction["actions"]
                    .as_array()
                    .filter(|rows| !rows.is_empty())
                {
                    for action in actions.iter().filter(|item| item.is_object()) {
                        append(&mut output, node.action(trigger, action)?)?;
                    }
                } else {
                    append(&mut output, node.fallback(trigger, false))?;
                }
            }
        } else if PythonJson::truthy(&node.target) {
            append(&mut output, node.fallback(&Value::Null, true))?;
        }
    }
    output.push(']');
    Some(json!({"interactions": output}))
}
