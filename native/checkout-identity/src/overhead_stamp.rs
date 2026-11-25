//! owner: OverheadStamp; allowed imports: std; forbidden imports: I/O/locale/timezone lookup;
//! callers/tests: OverheadSession; verification: common ISO timestamps and window comparisons.
#[path = "overhead_stamp_time.rs"]
mod clock;
use clock::OverheadStampTime;

#[derive(Clone)]
pub(crate) struct OverheadStamp {
    pub(crate) iso: String,
    ticks: i64,
    pub(crate) ordinal: i64,
    aware: bool,
}
impl OverheadStamp {
    /// Outer None is unproven grammar; inner None is a proven invalid datetime.
    pub(crate) fn parse(raw: &str) -> Option<Option<Self>> {
        let text = raw.replace('Z', "+00:00");
        let b = text.as_bytes();
        if b.len() < 4 || !b[..4].iter().all(u8::is_ascii_digit) {
            return Some(None);
        }
        if b.len() < 10 || b[4] != b'-' || b[7] != b'-' || !b[..10].is_ascii() {
            return None;
        }
        let Some((year, month, day, ordinal)) = Self::date(&text)? else {
            return Some(None);
        };
        let rest = &text[10..];
        let time = if let Some(separator) = rest.chars().next() {
            &rest[separator.len_utf8()..]
        } else {
            "00"
        };
        let (clock, zone) = time
            .find(['+', '-'])
            .map_or((time, None), |i| (&time[..i], Some(&time[i..])));
        let Some(time) = OverheadStampTime::parse(clock) else {
            return Some(None);
        };
        if time.hours > 23 || time.minutes > 59 || time.seconds > 59 {
            return Some(None);
        }
        let (offset, suffix) = if let Some(zone) = zone {
            let Some(parsed) = OverheadStampTime::suffix(zone) else {
                return Some(None);
            };
            parsed
        } else {
            (0, String::new())
        };
        let ticks = (ordinal * 86400 + time.second_count()) * 1_000_000 + time.micros - offset;
        let fraction = OverheadStampTime::fraction(time.micros);
        Some(Some(Self {
            iso: format!(
                "{year:04}-{month:02}-{day:02}T{:02}:{:02}:{:02}{fraction}{suffix}",
                time.hours, time.minutes, time.seconds,
            ),
            ticks,
            ordinal,
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
    fn digits(text: &str) -> Option<i64> {
        if !text.bytes().all(|b| b.is_ascii_digit()) || text.is_empty() {
            return None;
        }
        text.parse().ok()
    }
    pub(crate) fn compare(&self, other: &Self) -> Option<std::cmp::Ordering> {
        (self.aware == other.aware).then(|| self.ticks.cmp(&other.ticks))
    }
    pub(crate) fn ticks(&self) -> i64 {
        self.ticks
    }
    pub(crate) fn aware(&self) -> bool {
        self.aware
    }
}
