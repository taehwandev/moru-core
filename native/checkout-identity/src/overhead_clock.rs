//! owner: OverheadClock; allowed imports: pure timestamp parser, std clock/metadata;
//! forbidden imports: local timezone, providers, writes; callers/tests: report collector;
//! verification: UTC windows, Gregorian boundaries and Python mtime rounding.
use crate::overhead_stamp::OverheadStamp;
use serde_json::{json, Value};
use std::{
    fs::Metadata,
    os::unix::fs::MetadataExt,
    time::{SystemTime, UNIX_EPOCH},
};

pub(crate) struct OverheadClock {
    pub(crate) now: String,
    since: OverheadStamp,
    until: OverheadStamp,
}
impl OverheadClock {
    const DAY: i64 = 86_400_000_000;
    const EPOCH: i64 = 719163;
    pub(crate) fn new(since: Option<&str>, until: Option<&str>, days: i64) -> Option<Self> {
        let duration = SystemTime::now().duration_since(UNIX_EPOCH).ok()?;
        let micros = i64::try_from(duration.as_secs())
            .ok()?
            .checked_mul(1_000_000)?
            .checked_add(i64::from(duration.subsec_micros()))?;
        let now = Self::utc_iso(micros)?;
        Self::at(now, since, until, days)
    }
    fn at(now: String, since: Option<&str>, until: Option<&str>, days: i64) -> Option<Self> {
        let until = OverheadStamp::parse(until.filter(|s| !s.is_empty()).unwrap_or(&now))??;
        let since = if let Some(since) = since.filter(|s| !s.is_empty()) {
            OverheadStamp::parse(since)??
        } else {
            OverheadStamp::parse(&Self::shift_days(&until, days)?)??
        };
        Some(Self { now, since, until })
    }
    pub(crate) fn window(&self) -> [Value; 2] {
        [json!(self.since.iso), json!(self.until.iso)]
    }
    pub(crate) fn includes_mtime(&self, metadata: &Metadata) -> Option<bool> {
        if !self.since.aware() {
            return None;
        }
        // CPython stat creates its float with sec + 1e-9*nsec, then datetime
        // rounds the fractional second to microseconds with ties-to-even.
        let value = metadata.mtime() as f64 + 1e-9 * metadata.mtime_nsec() as f64;
        let whole = value.trunc();
        let micros = (value - whole) * 1_000_000.0;
        let ticks = (whole as i64)
            .checked_mul(1_000_000)?
            .checked_add(micros.round_ties_even() as i64)?;
        Self::utc_iso(ticks)?;
        Some(ticks.checked_add(Self::EPOCH * Self::DAY)? >= self.since.ticks())
    }
    fn shift_days(stamp: &OverheadStamp, days: i64) -> Option<String> {
        let zone = stamp.iso[10..].find(['+', '-']).map(|i| i + 10);
        let offset = if let Some(at) = zone {
            let z = &stamp.iso[at..];
            let seconds = z[1..3].parse::<i64>().ok()? * 3600 + z[4..6].parse::<i64>().ok()? * 60;
            seconds * 1_000_000 * if z.starts_with('-') { -1 } else { 1 }
        } else {
            0
        };
        let ordinal = stamp
            .ticks()
            .checked_add(offset)?
            .div_euclid(Self::DAY)
            .checked_sub(days)?;
        let (year, month, day) = Self::civil(ordinal)?;
        Some(format!("{year:04}-{month:02}-{day:02}{}", &stamp.iso[10..]))
    }
    fn utc_iso(unix_micros: i64) -> Option<String> {
        let ordinal = unix_micros.div_euclid(Self::DAY).checked_add(Self::EPOCH)?;
        let (year, month, day) = Self::civil(ordinal)?;
        let clock = unix_micros.rem_euclid(Self::DAY);
        let seconds = clock / 1_000_000;
        let micros = clock % 1_000_000;
        let fraction = if micros == 0 {
            String::new()
        } else {
            format!(".{micros:06}")
        };
        Some(format!(
            "{year:04}-{month:02}-{day:02}T{:02}:{:02}:{:02}{fraction}+00:00",
            seconds / 3600,
            seconds / 60 % 60,
            seconds % 60
        ))
    }
    fn prior(year: i64) -> i64 {
        let y = year - 1;
        365 * y + y / 4 - y / 100 + y / 400
    }
    fn civil(ordinal: i64) -> Option<(i64, i64, i64)> {
        if !(1..=3652059).contains(&ordinal) {
            return None;
        }
        let (mut low, mut high) = (1, 10000);
        while low + 1 < high {
            let mid = (low + high) / 2;
            if Self::prior(mid) < ordinal {
                low = mid;
            } else {
                high = mid;
            }
        }
        let leap = low % 4 == 0 && (low % 100 != 0 || low % 400 == 0);
        let lengths = [
            31,
            if leap { 29 } else { 28 },
            31,
            30,
            31,
            30,
            31,
            31,
            30,
            31,
            30,
            31,
        ];
        let mut left = ordinal - Self::prior(low);
        for (month, length) in lengths.into_iter().enumerate() {
            if left <= length {
                return Some((low, month as i64 + 1, left));
            }
            left -= length;
        }
        None
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn epoch_and_gregorian_limits() {
        assert_eq!(
            OverheadClock::utc_iso(0).as_deref(),
            Some("1970-01-01T00:00:00+00:00")
        );
        assert_eq!(
            OverheadClock::utc_iso(-1).as_deref(),
            Some("1969-12-31T23:59:59.999999+00:00")
        );
        assert_eq!(OverheadClock::civil(1), Some((1, 1, 1)));
        assert_eq!(OverheadClock::civil(3652059), Some((9999, 12, 31)));
    }
    #[test]
    fn shifts_preserve_local_time_and_offset() {
        for (until, days, since) in [
            (
                "2024-03-01T03:04:05.123+09:00",
                1,
                "2024-02-29T03:04:05.123000+09:00",
            ),
            ("2100-03-01T00:00:00Z", 1, "2100-02-28T00:00:00+00:00"),
            ("2000-02-28", -1, "2000-02-29T00:00:00"),
        ] {
            let clock =
                OverheadClock::at("2026-01-01T00:00:00+00:00".into(), None, Some(until), days)
                    .unwrap();
            assert_eq!(clock.since.iso, since);
        }
    }
}
