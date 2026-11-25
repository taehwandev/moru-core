//! owner: OverheadStamp; allowed imports: std; forbidden imports: I/O/locale/timezone lookup;
//! callers/tests: OverheadSession; verification: common ISO timestamps and window comparisons.
#[path = "overhead_stamp_time.rs"]
mod clock;
#[path = "overhead_stamp_date.rs"]
pub(crate) mod date;
use clock::OverheadStampTime;
use date::OverheadStampDate;

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
        let Some((date, rest)) = OverheadStampDate::parse_prefix(&text) else {
            return Some(None);
        };
        let OverheadStampDate {
            year,
            month,
            day,
            ordinal,
        } = date;
        let time = if let Some(separator) = rest.chars().next() {
            &rest[separator.len_utf8()..]
        } else {
            "00"
        };
        // Newer and older Python runtimes differ on some clock forms.
        // Defer embedded NULs and end-of-day midnight instead of classifying
        // them as invalid before the reference sees them.
        if time.contains('\0') {
            return None;
        }
        let (clock, zone) = time
            .find(['+', '-'])
            .map_or((time, None), |i| (&time[..i], Some(&time[i..])));
        let Some(time) = OverheadStampTime::parse(clock) else {
            return Some(None);
        };
        if time.hours == 24 && time.minutes == 0 && time.seconds == 0 && time.micros == 0 {
            return None;
        }
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
