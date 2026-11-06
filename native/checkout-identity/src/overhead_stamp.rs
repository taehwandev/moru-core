//! owner: OverheadStamp; allowed imports: std; forbidden imports: I/O/locale/timezone lookup;
//! callers/tests: OverheadSession; verification: common ISO timestamps and window comparisons.
#[derive(Clone)]
pub(super) struct OverheadStamp {
    pub(super) iso: String,
    ticks: i64,
    aware: bool,
}
impl OverheadStamp {
    /// Outer None is unproven grammar; inner None is a proven invalid datetime.
    pub(super) fn parse(raw: &str) -> Option<Option<Self>> {
        let text = raw.replace('Z', "+00:00");
        let b = text.as_bytes();
        if b.len() < 4 || !b[..4].iter().all(u8::is_ascii_digit) {
            return Some(None);
        }
        if !text.is_ascii() || b.len() < 10 || b[4] != b'-' || b[7] != b'-' {
            return None;
        }
        let Some((year, month, day, ordinal)) = Self::date(&text)? else {
            return Some(None);
        };
        let mut rest = &text[10..];
        if !rest.is_empty() {
            if !rest.starts_with(['T', ' ']) {
                return None;
            }
            rest = &rest[1..];
            if rest.is_empty() {
                return Some(None);
            }
        }
        let zone_at = rest.find(['+', '-']);
        let (clock, zone) = zone_at.map_or((rest, None), |i| (&rest[..i], Some(&rest[i..])));
        if !rest.is_empty() && clock.is_empty() {
            return Some(None);
        }
        let (clock, fraction) = clock
            .split_once('.')
            .map_or((clock, None), |(a, b)| (a, Some(b)));
        let pieces: Vec<_> = clock.split(':').collect();
        if !clock.is_empty() && (pieces.len() > 3 || pieces.iter().any(|s| s.len() != 2)) {
            return None;
        }
        let mut fields = [0i64; 3];
        if !clock.is_empty() {
            for (i, value) in pieces.iter().enumerate() {
                let Some(value) = Self::digits(value) else {
                    return Some(None);
                };
                fields[i] = value;
            }
        }
        if fields[0] > 23 || fields[1] > 59 || fields[2] > 59 {
            return Some(None);
        }
        let micros = if let Some(fraction) = fraction {
            if pieces.len() != 3 || !matches!(fraction.len(), 3 | 6) {
                return None;
            }
            let Some(value) = Self::digits(fraction) else {
                return Some(None);
            };
            value * if fraction.len() == 3 { 1000 } else { 1 }
        } else {
            0
        };
        let Some((offset, suffix)) = Self::zone(zone)? else {
            return Some(None);
        };
        let ticks = ((ordinal * 86400 + fields[0] * 3600 + fields[1] * 60 + fields[2] - offset)
            * 1_000_000)
            + micros;
        let fractional = if micros != 0 {
            format!(".{micros:06}")
        } else {
            String::new()
        };
        Some(Some(Self {
            iso: format!(
                "{year:04}-{month:02}-{day:02}T{:02}:{:02}:{:02}{fractional}{suffix}",
                fields[0], fields[1], fields[2]
            ),
            ticks,
            aware: zone.is_some(),
        }))
    }
    fn date(text: &str) -> Option<Option<(i64, i64, i64, i64)>> {
        let year = Self::digits(&text[0..4])?;
        let Some(month) = Self::digits(&text[5..7]) else {
            return Some(None);
        };
        let Some(day) = Self::digits(&text[8..10]) else {
            return Some(None);
        };
        let leap = year % 4 == 0 && (year % 100 != 0 || year % 400 == 0);
        let days = [
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
        if year == 0 || !(1..=12).contains(&month) || day == 0 || day > days[(month - 1) as usize] {
            return Some(None);
        }
        let prior = year - 1;
        let ordinal = 365 * prior + prior / 4 - prior / 100
            + prior / 400
            + days[..(month - 1) as usize].iter().sum::<i64>()
            + day;
        Some(Some((year, month, day, ordinal)))
    }
    fn zone(zone: Option<&str>) -> Option<Option<(i64, String)>> {
        let pair = if let Some(zone) = zone {
            if zone.len() != 6 || zone.as_bytes()[3] != b':' {
                return None;
            }
            let Some(hours) = Self::digits(&zone[1..3]) else {
                return Some(None);
            };
            let Some(minutes) = Self::digits(&zone[4..6]) else {
                return Some(None);
            };
            // Python normalizes minute overflow; keep unfamiliar offsets with Python.
            if minutes > 59 {
                return None;
            }
            if hours > 23 {
                return Some(None);
            }
            let offset = (hours * 60 + minutes) * 60 * if zone.starts_with('-') { -1 } else { 1 };
            (
                offset,
                if offset == 0 {
                    "+00:00".into()
                } else {
                    zone.to_owned()
                },
            )
        } else {
            (0, String::new())
        };
        Some(Some(pair))
    }
    fn digits(text: &str) -> Option<i64> {
        if !text.bytes().all(|b| b.is_ascii_digit()) || text.is_empty() {
            return None;
        }
        text.parse().ok()
    }
    pub(super) fn compare(&self, other: &Self) -> Option<std::cmp::Ordering> {
        (self.aware == other.aware).then(|| self.ticks.cmp(&other.ticks))
    }
}
