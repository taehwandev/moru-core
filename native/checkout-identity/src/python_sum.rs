//! owner: PythonSum; allowed imports: shared JSON numbers, SumFloat/std;
//! forbidden imports: I/O/version guesses; callers/tests: FigmaCoverage, overhead statistics;
//! verification: builder-profile numeric sum parity.
#[path = "python_sum_float.rs"]
mod floating;
use crate::python_json::{Number, Value};
use floating::SumFloat;
pub(crate) struct PythonSum;
impl PythonSum {
    pub(crate) fn sum<'a>(values: impl Iterator<Item = &'a Value>) -> Option<Value> {
        let mut integer = "0".to_owned();
        let mut floating: Option<SumFloat> = None;
        let mut fast = true;
        for value in values {
            let Value::Number(number) = value else {
                continue;
            };
            if let Some(total) = floating.as_mut() {
                total.add(number)?;
                continue;
            }
            match number {
                Number::Integer(text) => {
                    let total = Self::add(&integer, text);
                    fast &= SumFloat::fits_long(text) && SumFloat::fits_long(&total);
                    integer = total;
                }
                Number::Float(value) => floating = Some(SumFloat::new(&integer, *value, fast)?),
            }
        }
        Some(Value::Number(match floating {
            Some(total) => Number::Float(total.finish()),
            // Python can reject report formatting after an otherwise valid integer sum.
            None => Number::from_token(
                &integer,
                env!("MORU_PYTHON_INT_MAX_STR_DIGITS").parse().ok()?,
            )?,
        }))
    }
    fn add(a: &str, b: &str) -> String {
        let an = a.starts_with('-');
        let bn = b.starts_with('-');
        let a = a.trim_start_matches('-');
        let b = b.trim_start_matches('-');
        if an == bn {
            return Self::signed(Self::unsigned_add(a, b), an);
        }
        let order = a.len().cmp(&b.len()).then_with(|| a.cmp(b));
        match order {
            std::cmp::Ordering::Equal => "0".into(),
            std::cmp::Ordering::Greater => Self::signed(Self::subtract(a, b), an),
            std::cmp::Ordering::Less => Self::signed(Self::subtract(b, a), bn),
        }
    }
    fn signed(text: String, negative: bool) -> String {
        if negative && text != "0" {
            format!("-{text}")
        } else {
            text
        }
    }
    fn unsigned_add(a: &str, b: &str) -> String {
        let a = a.as_bytes();
        let b = b.as_bytes();
        let mut out = Vec::new();
        let mut carry = 0;
        for offset in 0..a.len().max(b.len()) {
            let x = a.len().checked_sub(offset + 1).map_or(0, |i| a[i] - b'0');
            let y = b.len().checked_sub(offset + 1).map_or(0, |i| b[i] - b'0');
            let total = x + y + carry;
            out.push(b'0' + total % 10);
            carry = total / 10;
        }
        if carry > 0 {
            out.push(b'0' + carry);
        }
        out.reverse();
        String::from_utf8(out).unwrap()
    }
    fn subtract(a: &str, b: &str) -> String {
        let a = a.as_bytes();
        let b = b.as_bytes();
        let mut out = Vec::new();
        let mut borrow = 0i8;
        for offset in 0..a.len() {
            let x = (a[a.len() - offset - 1] - b'0') as i8;
            let y = b.len().checked_sub(offset + 1).map_or(0, |i| b[i] - b'0') as i8;
            let mut digit = x - y - borrow;
            borrow = i8::from(digit < 0);
            if digit < 0 {
                digit += 10;
            }
            out.push(b'0' + digit as u8);
        }
        while out.len() > 1 && out.last() == Some(&b'0') {
            out.pop();
        }
        out.reverse();
        String::from_utf8(out).unwrap()
    }
}

#[cfg(test)]
#[path = "figma_coverage_sum_tests.rs"]
mod tests;
