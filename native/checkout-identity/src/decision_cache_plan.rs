//! owner: canonical research decision request sizing and cache identity.
//! allowed imports: bounded JSON, Python JSON serialization, SHA-256 and decision cache operations.
//! forbidden imports: provider calls, credentials and direct filesystem writes.
//! callers/tests: microsoft_decision.py; test_decision_cache_plan.
//! verification: exact Python digest and byte length for existing caches.
use crate::{
    atomic_sibling::AtomicSibling,
    decision_cached_result::DecisionCachedResult,
    decision_cli::DecisionCli,
    decision_input::DecisionInput,
    decision_report::DecisionReport,
    decision_response::DecisionResponse,
    pretool_guard::CallbackGuard,
    python_encoding::PythonEncoding,
    python_json::{Number, Object, PythonJson, Value as PythonValue},
};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    ffi::OsString,
    io::{self, Read, Write},
    path::Path,
    time::{SystemTime, UNIX_EPOCH},
};

const MAX_MESSAGE: usize = 1024 * 1024;
const MAX_CANONICAL_BYTES: usize = 4 * MAX_MESSAGE;
const CLI_CONTRACT: &str = include_str!("../../../scripts/research-triage/decision_contract.json");

pub(crate) struct DecisionCachePlan;

impl DecisionCachePlan {
    pub(crate) fn alias(launcher: &OsString, args: &[OsString]) -> Option<i32> {
        if !PythonEncoding::utf8() || CallbackGuard::root(launcher, "microsoft-decision").is_none()
        {
            return None;
        }
        let argv: Vec<_> = args.iter().map(|arg| arg.to_str()).collect::<Option<_>>()?;
        if argv.iter().map(|arg| arg.len() + 1).sum::<usize>() > MAX_MESSAGE {
            return None;
        }
        let mut request: Value = serde_json::from_str(CLI_CONTRACT).ok()?;
        request["argv"] = json!(argv);
        // Defer larger integers to the Python caller, which owns its runtime limit.
        request["digit_limit"] = json!(640);
        let reply = Self::read_only_cli(request)?;
        let text = reply["text"].as_str()?;
        if text.len() > MAX_MESSAGE {
            return None;
        }
        let mut output = io::stdout().lock();
        Some(i32::from(
            writeln!(output, "{text}")
                .and_then(|_| output.flush())
                .is_err(),
        ))
    }

    pub(crate) fn run(launcher: &OsString, args: &[OsString]) -> i32 {
        if args.len() != 2
            || !matches!(
                args[1].to_str(),
                Some(
                    "prepare"
                        | "validate-prepare"
                        | "read-prepare-input"
                        | "read-only-report"
                        | "read-only-cli"
                        | "summarize"
                        | "validate-response"
                        | "validate-cached"
                        | "read-cached-file"
                        | "cache-write-support"
                        | "write-cached-file"
                )
            )
            || CallbackGuard::root(launcher, "decision-cache-plan").is_none()
        {
            return 125;
        }
        let mut raw = Vec::new();
        if io::stdin()
            .take((MAX_MESSAGE + 1) as u64)
            .read_to_end(&mut raw)
            .is_err()
            || raw.len() > MAX_MESSAGE
        {
            return 125;
        }
        let Some(result) = serde_json::from_slice(&raw).ok().and_then(|value| {
            if args[1] == "summarize" {
                return DecisionReport::summarize(&value);
            }
            if args[1] == "validate-response" {
                return DecisionResponse::verdict(&value);
            }
            if args[1] == "validate-cached" {
                return DecisionCachedResult::verdict(&value);
            }
            if args[1] == "read-cached-file" {
                return DecisionCachedResult::read(&value);
            }
            if args[1] == "cache-write-support" {
                return Some(json!({"supported": true, "create_directory": true}));
            }
            if args[1] == "write-cached-file" {
                return DecisionCachedResult::replace(&value);
            }
            if args[1] == "read-prepare-input" {
                return Self::prepare_file(value);
            }
            if args[1] == "read-only-report" {
                return Self::read_only_report(&value);
            }
            if args[1] == "read-only-cli" {
                return Self::read_only_cli(value);
            }
            if args[1] == "validate-prepare" {
                if let Err(error) = DecisionInput::validate(&value) {
                    return Some(json!({"error": error}));
                }
            }
            Self::prepare(&value).map(|rows| json!({"rows": rows}))
        }) else {
            return 125;
        };
        let reply_failure = if args[1] == "write-cached-file" {
            1
        } else {
            125
        };
        let Ok(reply) = serde_json::to_vec(&json!({"schema_version": 1, "result": result})) else {
            return reply_failure;
        };
        if reply.len() > MAX_MESSAGE {
            return reply_failure;
        }
        i32::from(io::stdout().write_all(&reply).is_err())
    }

    fn prepare_file(mut request: Value) -> Option<Value> {
        let path = Path::new(request.get("path")?.as_str()?);
        let input = DecisionInput::read(path)?;
        if let Err(error) = DecisionInput::validate(&input) {
            return Some(json!({"error": error}));
        }
        let input = DecisionInput::project(&input)?;
        request["query"] = input["query"].clone();
        request["sources"] = input["sources"].clone();
        let rows = Self::prepare(&request)?;
        Some(json!({"payload": input, "rows": rows}))
    }

    fn read_only_cli(mut request: Value) -> Option<Value> {
        let cli = DecisionCli::parse(&request)?;
        let digit_limit = request.get("digit_limit")?.as_u64()?;
        let schema = request.get("schema")?.as_i64()?;
        let options: Vec<_> = request["questions"]["source_kind"]["criteria"]
            .as_object()?
            .keys()
            .cloned()
            .collect();
        request["path"] = json!(cli.input.to_str()?);
        request["model"] = json!(cli.model);
        let prepared = Self::prepare_file(request)?;
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .ok()?
            .as_secs_f64();
        let rows = prepared["rows"].as_array()?;
        let sources = prepared["payload"]["sources"].as_array()?;
        let sources: Vec<_> = sources
            .iter()
            .zip(rows)
            .map(|(source, plan)| {
                json!([
                    source["id"],
                    source["url"],
                    source["required"].as_bool().unwrap_or(false),
                    plan[0]
                ])
            })
            .collect();
        Self::read_only_report(&json!({
            "model": cli.model, "refresh": cli.refresh, "digit_limit": digit_limit, "sources": sources,
            "cache": {"directory": cli.cache_dir.to_str()?, "schema": schema, "now": now,
                      "ttl": cli.ttl, "options": options},
        }))
    }

    fn read_only_report(request: &Value) -> Option<Value> {
        let sources = request.get("sources")?.as_array()?;
        let model = request.get("model")?.as_str()?;
        let digit_limit = usize::try_from(request.get("digit_limit")?.as_u64()?).ok()?;
        let refresh = request.get("refresh")?.as_bool()?;
        let cache = request.get("cache")?.as_object()?;
        let directory = if refresh || sources.is_empty() {
            None
        } else {
            match AtomicSibling::open_directory_result(Path::new(cache.get("directory")?.as_str()?))
            {
                Ok(dir) => Some(dir),
                Err(error) if error.kind() == io::ErrorKind::NotFound => None,
                Err(_) => return None,
            }
        };
        let cache = Value::Object(cache.clone());
        let mut results = Vec::with_capacity(sources.len());
        let mut cached = Vec::with_capacity(sources.len());
        let mut ranking = Vec::with_capacity(sources.len());
        let mut cache_hits = 0;
        let mut cache_bytes = 0;
        for source in sources {
            let [id, url, required, key] = source.as_array()?.as_slice() else {
                return None;
            };
            let (id, url, required, key) = (
                id.as_str()?,
                url.as_str()?,
                required.as_bool()?,
                key.as_str()?,
            );
            let mut row = json!({"id": id, "url": url, "required": required});
            let (verdict, relevance) = if let Some(directory) = &directory {
                DecisionCachedResult::read_in(directory, key, &cache)?
            } else {
                (json!({"hit": false}), 0.0)
            };
            let hit = verdict["hit"].as_bool()?;
            ranking.push(json!([required, !hit, relevance]));
            if hit {
                cache_bytes += serde_json::to_vec(&verdict).ok()?.len();
                if cache_bytes > MAX_MESSAGE {
                    return None;
                }
                cache_hits += 1;
                row["status"] = json!("cached");
                cached.push(verdict);
            } else {
                row["status"] = json!("unscored");
                row["reason"] = json!("cache_miss");
                cached.push(Value::Null);
            }
            results.push(row);
        }
        let summary = DecisionReport::summarize(&json!({"rows": ranking}))?;
        let ranked_ids: Option<Vec<&str>> = summary["order"]
            .as_array()?
            .iter()
            .map(|index| results.get(index.as_u64()? as usize)?.get("id")?.as_str())
            .collect();
        let report = json!({
            "model": model, "network_calls": 0, "cache_hits": cache_hits,
            "unscored": summary["unscored"], "new_reported_cost_usd": null,
            "cost_complete": true, "warnings": [], "results": results, "ranked_ids": ranked_ids?,
        });
        let text = DecisionReport::encode_cache_only(&report, &cached, digit_limit)?;
        Some(json!({"text": text}))
    }

    fn prepare(input: &Value) -> Option<Vec<Value>> {
        let query = input.get("query")?.as_str()?;
        let model = input.get("model")?.as_str()?;
        let endpoint = input.get("endpoint")?.as_str()?;
        let schema = input.get("schema")?.as_i64()?;
        let questions = input.get("questions")?.as_object()?;
        let mut total = 0usize;
        input
            .get("sources")?
            .as_array()?
            .iter()
            .map(|source| {
                let source: serde_json::Map<_, _> = source
                    .as_object()?
                    .iter()
                    .filter(|(key, _)| {
                        ["url", "title", "text", "published_at"].contains(&key.as_str())
                    })
                    .map(|(key, value)| (key.clone(), value.clone()))
                    .collect();
                if !source.values().all(Value::is_string) {
                    return None;
                }
                let request = json!({
                    "model": model, "state": {"query": query, "source": source},
                    "questions": questions, "provider": {"allow_fallbacks": false},
                });
                let bytes = encode(&request)?.len();
                total = total.checked_add(bytes)?;
                if total > MAX_CANONICAL_BYTES {
                    return None;
                }
                let cached = &json!({"schema": schema, "endpoint": endpoint, "request": request});
                let key = format!("{:x}", Sha256::digest(encode(cached)?));
                Some(json!([key, bytes]))
            })
            .collect()
    }
}

fn encode(value: &Value) -> Option<String> {
    PythonJson::render(&sorted_value(value)?, false, false)
}

fn sorted_value(value: &Value) -> Option<PythonValue> {
    match value {
        Value::Object(map) => {
            let mut entries: Vec<_> = map.iter().collect();
            entries.sort_unstable_by(|(a, _), (b, _)| a.cmp(b));
            let mut ordered = Object::new();
            for (key, value) in entries {
                ordered.insert(key.clone(), sorted_value(value)?);
            }
            Some(PythonValue::Object(ordered))
        }
        Value::Array(items) => Some(PythonValue::Array(
            items.iter().map(sorted_value).collect::<Option<_>>()?,
        )),
        Value::Number(number) if number.is_i64() || number.is_u64() => Some(PythonValue::Number(
            Number::from_token(&number.to_string(), 0)?,
        )),
        Value::Number(_) => None,
        Value::Null => Some(PythonValue::Null),
        Value::Bool(value) => Some(PythonValue::Bool(*value)),
        Value::String(value) => Some(PythonValue::String(value.clone())),
    }
}
