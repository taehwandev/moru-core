//! owner: OverheadStampTime; allowed imports: std; forbidden imports: I/O and local timezone;
//! callers/tests: OverheadStamp, report CLI and session parity; verification: ISO clocks and UTC offsets.

pub(super) struct OverheadStampTime {
    pub(super) hours: i64,
    pub(super) minutes: i64,
    pub(super) seconds: i64,
    pub(super) micros: i64,
}

impl OverheadStampTime {
    pub(super) fn parse(raw: &str) -> Option<Self> {
        let (clock, fraction) = raw
            .split_once(['.', ','])
            .map_or((raw, None), |(clock, fraction)| (clock, Some(fraction)));
        if clock.len() > 8 || !clock.is_ascii() {
            return None;
        }
        let fields = if clock.contains(':') {
            clock.split(':').collect::<Vec<_>>()
        } else {
            if clock.len() % 2 != 0 {
                return None;
            }
            (0..clock.len())
                .step_by(2)
                .map(|index| &clock[index..index + 2])
                .collect()
        };
        if fields.is_empty() || fields.len() > 3 {
            return None;
        }
        let mut values = [0; 3];
        for (index, value) in fields.iter().enumerate() {
            if value.len() != 2 {
                return None;
            }
            values[index] = Self::digits(value)?;
        }
        let micros = if let Some(fraction) = fraction {
            if fields.len() != 3 || !fraction.bytes().all(|b| b.is_ascii_digit()) {
                return None;
            }
            let width = fraction.len().min(6);
            Self::digits(&fraction[..width])? * 10i64.pow((6 - width) as u32)
        } else {
            0
        };
        Some(Self {
            hours: values[0],
            minutes: values[1],
            seconds: values[2],
            micros,
        })
    }

    pub(super) fn second_count(&self) -> i64 {
        self.hours * 3600 + self.minutes * 60 + self.seconds
    }

    pub(super) fn suffix(zone: &str) -> Option<(i64, String)> {
        let time = Self::parse(&zone[1..])?;
        let seconds = time.second_count();
        if seconds == 0 {
            // datetime uses the UTC singleton for zero whole-second offsets.
            return Some((0, "+00:00".into()));
        }
        if seconds >= 86400 {
            return None;
        }
        let sign = &zone[..1];
        let mut suffix = format!("{sign}{:02}:{:02}", seconds / 3600, seconds / 60 % 60);
        if seconds % 60 != 0 || time.micros != 0 {
            suffix.push_str(&format!(
                ":{:02}{}",
                seconds % 60,
                Self::fraction(time.micros)
            ));
        }
        let ticks = seconds * 1_000_000 + time.micros;
        Some((if sign == "-" { -ticks } else { ticks }, suffix))
    }

    pub(super) fn fraction(micros: i64) -> String {
        if micros == 0 {
            String::new()
        } else {
            format!(".{micros:06}")
        }
    }

    fn digits(text: &str) -> Option<i64> {
        if text.is_empty() || !text.bytes().all(|b| b.is_ascii_digit()) {
            return None;
        }
        text.parse().ok()
    }
}
