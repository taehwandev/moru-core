//! owner: CoverageSum; allowed imports: shared JSON numbers/std; forbidden imports:
//! I/O/version guesses; callers/tests: FigmaCoverage; verification: exact numeric sums.
use crate::python_json::{Number, Value};
pub(super) struct CoverageSum;
impl CoverageSum {
    pub(super) fn sum<'a>(values: impl Iterator<Item = &'a Value>) -> Option<Value> {
        let mut integer = "0".to_owned();
        let mut floating = None;
        for value in values {
            let Value::Number(number) = value else {
                continue;
            };
            match (number, floating) {
                (Number::Integer(text), None) => integer = Self::add(&integer, text),
                _ => {
                    let previous = match floating {
                        Some(value) => value,
                        None => Self::small_integer(&integer)?,
                    };
                    let next = match number {
                        Number::Integer(text) => Self::small_integer(text)?,
                        Number::Float(value) => *value,
                    };
                    floating = Some(Self::exact_add(previous, next)?);
                }
            }
        }
        Some(Value::Number(match floating {
            Some(value) => Number::Float(value),
            // The report formats this integer; Python's conversion digit limit
            // can reject a sum even when every individual input was admissible.
            None => Number::from_token(
                &integer,
                env!("MORU_PYTHON_INT_MAX_STR_DIGITS").parse().ok()?,
            )?,
        }))
    }

    fn small_integer(text: &str) -> Option<f64> {
        let value = text.parse::<i64>().ok()?;
        (value.unsigned_abs() <= (1u64 << 53)).then_some(value as f64)
    }

    fn exact_add(a: f64, b: f64) -> Option<f64> {
        let sum = a + b;
        if !a.is_finite() || !b.is_finite() || !sum.is_finite() {
            return None;
        }
        // Error-free TwoSum: admit only zero rounding residual. This avoids the
        // Python 3.12 compensated-summation difference without changing policy.
        let b_virtual = sum - a;
        let error = (a - (sum - b_virtual)) + (b - b_virtual);
        (error == 0.0).then_some(sum)
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
