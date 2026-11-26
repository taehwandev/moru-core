//! Owner: UTC normalization for ordinary Spill timestamp strings.
//! Allowed: existing Python whitespace and ISO date/clock grammar.
//! Forbidden: clocks, locale lookup, files, databases and provider APIs.
//! Callers/tests: status_trend_sqlite and synthetic trend report parity.
use crate::{
    overhead_stamp::{date::OverheadStampDate, OverheadStamp},
    python_text::PythonText,
};

const MICROS_PER_SECOND: i64 = 1_000_000;
const MICROS_PER_DAY: i64 = 86_400 * MICROS_PER_SECOND;

pub(super) fn utc(raw: &str) -> Option<String> {
    let text = raw.trim_matches(PythonText::whitespace);
    if text.is_empty() {
        return Some(String::new());
    }
    // Admit only the telemetry clock profile shared by supported Python hosts.
    // Legacy values outside this grammar retain the reference behavior.
    let (head, tail) = text.as_bytes().split_at_checked(19)?;
    if !head
        .iter()
        .copied()
        .enumerate()
        .all(|(index, byte)| match index {
            4 | 7 => byte == b'-',
            10 => matches!(byte, b'T' | b' '),
            13 | 16 => byte == b':',
            _ => byte.is_ascii_digit(),
        })
        || &head[11..13] >= b"24"
    {
        return None;
    }
    let suffix = if let Some(fraction) = tail.strip_prefix(b".") {
        let digits = fraction
            .iter()
            .take_while(|byte| byte.is_ascii_digit())
            .count();
        // Python 3.9 accepts exactly three or six fractional digits.
        if !matches!(digits, 3 | 6) {
            return None;
        }
        &fraction[digits..]
    } else {
        tail
    };
    match suffix {
        b"" | b"Z" => {}
        [b'+' | b'-', hour1, hour2, b':', minute1, minute2]
            if [hour1, hour2, minute1, minute2]
                .into_iter()
                .all(u8::is_ascii_digit)
                && (*hour1 - b'0') * 10 + (*hour2 - b'0') < 24
                && *minute1 <= b'5' => {}
        _ => return None,
    }
    let ticks = OverheadStamp::parse(text)??.ticks();
    let date = OverheadStampDate::from_ordinal(ticks.div_euclid(MICROS_PER_DAY))?;
    let within_day = ticks.rem_euclid(MICROS_PER_DAY);
    let seconds = within_day / MICROS_PER_SECOND;
    let micros = within_day % MICROS_PER_SECOND;
    let fraction = if micros == 0 {
        String::new()
    } else {
        format!(".{micros:06}")
    };
    Some(format!(
        "{:04}-{:02}-{:02}T{:02}:{:02}:{:02}{fraction}+00:00",
        date.year,
        date.month,
        date.day,
        seconds / 3600,
        (seconds / 60) % 60,
        seconds % 60,
    ))
}
