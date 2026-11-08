//! owner: CardWriteProcess; allowed imports: serde, guarded card transaction,
//! existing source/state/UTC readers; forbidden imports: Python, SQL, creation,
//! schema changes, arbitrary paths, retry; callers/tests: private launcher probe,
//! test_native_card_write and transported consumer; verification: no post-DML 125.
use crate::{
    cards_process::CardsProcess, cards_transaction::CardTransaction, overhead_clock::OverheadClock,
    overhead_stamp::OverheadStamp, pretool_guard::CallbackGuard, python_text::PythonText,
    statusline::Renderer,
};
use serde_json::{json, Value};
use std::{
    env,
    ffi::OsString,
    io::{Read, Write},
    path::Path,
};

pub(crate) struct CardWriteProcess;

impl CardWriteProcess {
    pub(crate) fn run(launcher: &OsString, args: &[OsString]) -> i32 {
        // Capability negotiation is read-only, including on a stale source root.
        // A writer still independently validates the current source/environment.
        if args.len() == 2 && args[1] == "ready" {
            return if std::io::stdout()
                .write_all(b"{\"schema_version\":1,\"ready\":true}")
                .is_ok()
            {
                0
            } else {
                1
            };
        }
        if args.len() != 2
            || !matches!(args[1].to_str(), Some("open" | "settle"))
            || CallbackGuard::root(launcher, "git").is_none()
            || !test_store_allowed()
        {
            return 125;
        }
        let mut bytes = Vec::new();
        if std::io::stdin()
            .take(65537)
            .read_to_end(&mut bytes)
            .is_err()
            || bytes.len() > 65536
        {
            return 125;
        }
        let Some((values, cutoff, foreign_keys)) = input(&bytes, args[1] == "open") else {
            return 125;
        };
        let Some(home) = CardsProcess::state_home() else {
            return 125;
        };
        let Some(store) =
            CardTransaction::prepared(&home.join("work-cards/cards.sqlite3"), foreign_keys)
        else {
            return 125;
        };
        // Every refusal above precedes DML. No execution path below returns 125.
        let result = if let Some(cutoff) = cutoff {
            let values: [String; 10] = values.try_into().expect("validated open values");
            store.upsert(&values, &cutoff)
        } else {
            store.settle(&values[2], &values[3], &values[0], &values[1])
        };
        let packet = match result {
            Ok(changed) => json!({"schema_version":1,"result":{"changed":changed}}),
            Err(rusqlite::Error::SqliteFailure(code, message)) => json!({"schema_version":1,
                "error":{"code":code.extended_code,"message":message.unwrap_or_else(|| code.to_string())}}),
            Err(_) => return 1,
        };
        match serde_json::to_vec(&packet) {
            Ok(bytes) if bytes.len() <= 65536 && std::io::stdout().write_all(&bytes).is_ok() => 0,
            _ => 1,
        }
    }
}

fn test_store_allowed() -> bool {
    let testing = env::var("MORU_UNDER_UNITTEST")
        .map(|v| !Renderer::strip(&v).is_empty())
        .unwrap_or_else(|e| matches!(e, env::VarError::NotUnicode(_)));
    !testing || env::var("MORU_STATE_HOME").is_ok_and(|v| !Renderer::strip(&v).is_empty())
}

fn input(bytes: &[u8], open: bool) -> Option<(Vec<String>, Option<String>, bool)> {
    let packet: Value = serde_json::from_slice(bytes).ok()?;
    let fields = packet.as_object()?;
    if fields.len() != 2 {
        return None;
    }
    let foreign_keys = fields.get("foreign_keys")?.as_bool()?;
    let values: Vec<String> = fields
        .get("values")?
        .as_array()?
        .iter()
        .map(|v| v.as_str().map(str::to_owned))
        .collect::<Option<_>>()?;
    if open {
        if values.len() != 10
            || !hex(&values[0], 24)
            || !hex(&values[1], 32)
            || !hex(&values[7], 32)
            || values[2].is_empty()
            || values[2].chars().count() > 200
            || !values[2].chars().all(PythonText::printable)
            || !Path::new(&values[4]).is_absolute()
            || values[4].contains('\0')
            || values[5] != values[6]
            || !stamp(&values[5])
        {
            return None;
        }
        // Underflow declines before DML, so Python retains INSERT-before-cutoff
        // error priority and its original rollback behavior.
        let clock = OverheadClock::new(None, Some(&values[5]), 90)?;
        let cutoff = clock.window()[0].as_str()?.to_owned();
        Some((values, Some(cutoff), foreign_keys))
    } else {
        if values.len() != 4
            || !matches!(values[0].as_str(), "done" | "cancelled")
            || !stamp(&values[1])
            || !hex(&values[2], 24)
            || !hex(&values[3], 32)
        {
            return None;
        }
        Some((values, None, foreign_keys))
    }
}

fn hex(text: &str, length: usize) -> bool {
    text.len() == length
        && text
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}

fn stamp(text: &str) -> bool {
    (text.len() == 19 || text.len() == 26 || text.ends_with("+00:00"))
        && OverheadStamp::parse(text)
            .flatten()
            .is_some_and(|s| s.iso == text)
}
