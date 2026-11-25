//! owner: OverheadStampDate; allowed imports: std; forbidden imports: I/O and local timezones;
//! callers/tests: OverheadStamp and OverheadClock; verification: Gregorian and ISO week dates.

pub(crate) struct OverheadStampDate {
    pub(crate) year: i64,
    pub(crate) month: i64,
    pub(crate) day: i64,
    pub(crate) ordinal: i64,
}

impl OverheadStampDate {
    pub(super) fn parse_prefix(text: &str) -> Option<(Self, &str)> {
        let year = Self::digits(text.get(..4)?)?;
        if year == 0 {
            return None;
        }
        let rest = &text[4..];
        if let Some(week) = rest.strip_prefix("-W") {
            return Self::week(year, week, true);
        }
        if let Some(week) = rest.strip_prefix('W') {
            return Self::week(year, week, false);
        }
        let separated = rest.starts_with('-');
        let rest = rest.strip_prefix('-').unwrap_or(rest);
        let month = Self::digits(rest.get(..2)?)?;
        let rest = if separated {
            rest[2..].strip_prefix('-')?
        } else {
            &rest[2..]
        };
        let day = Self::digits(rest.get(..2)?)?;
        let days = Self::month_lengths(year);
        let month_index = usize::try_from(month - 1).ok()?;
        if day == 0 || day > *days.get(month_index)? {
            return None;
        }
        let ordinal = Self::prior(year) + days[..month_index].iter().sum::<i64>() + day;
        Some((
            Self {
                year,
                month,
                day,
                ordinal,
            },
            &rest[2..],
        ))
    }

    fn week(year: i64, text: &str, separated: bool) -> Option<(Self, &str)> {
        let week = Self::digits(text.get(..2)?)?;
        let rest = &text[2..];
        let has_weekday = if separated {
            // A hyphen followed by two digits starts a clock, as in
            // 2020-W01-12:34. Otherwise a hyphen introduces a weekday.
            rest.starts_with('-') && !rest.as_bytes().get(2).is_some_and(u8::is_ascii_digit)
        } else {
            // A numeric date/time separator can be part of a run of digits.
            // Clock fields are pairs, with one extra digit for that separator.
            let digits = rest.bytes().take_while(u8::is_ascii_digit).count();
            digits == 1 || (digits > 1 && digits % 2 == 0)
        };
        let (weekday, rest) = if has_weekday {
            let day = &rest[usize::from(separated)..];
            (Self::digits(day.get(..1)?)?, &day[1..])
        } else {
            (1, rest)
        };
        let monday = Self::week_one_monday(year);
        let weeks = (Self::week_one_monday(year + 1) - monday) / 7;
        if !(1..=weeks).contains(&week) || !(1..=7).contains(&weekday) {
            return None;
        }
        let date = Self::from_ordinal(monday + (week - 1) * 7 + weekday - 1)?;
        Some((date, rest))
    }

    pub(crate) fn from_ordinal(ordinal: i64) -> Option<Self> {
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
        let mut day = ordinal - Self::prior(low);
        for (month_index, days) in Self::month_lengths(low).into_iter().enumerate() {
            if day <= days {
                return Some(Self {
                    year: low,
                    month: month_index as i64 + 1,
                    day,
                    ordinal,
                });
            }
            day -= days;
        }
        None
    }

    fn week_one_monday(year: i64) -> i64 {
        let january_fourth = Self::prior(year) + 4;
        january_fourth - (january_fourth - 1) % 7
    }

    fn prior(year: i64) -> i64 {
        let y = year - 1;
        365 * y + y / 4 - y / 100 + y / 400
    }

    fn month_lengths(year: i64) -> [i64; 12] {
        let leap = year % 4 == 0 && (year % 100 != 0 || year % 400 == 0);
        [
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
        ]
    }

    fn digits(text: &str) -> Option<i64> {
        if text.is_empty() || !text.bytes().all(|b| b.is_ascii_digit()) {
            return None;
        }
        text.parse().ok()
    }
}
