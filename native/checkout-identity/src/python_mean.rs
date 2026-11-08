//! owner: PythonMean; allowed imports: std; forbidden imports: I/O, runtime Python;
//! callers/tests: native overhead statistics; verification: exact finite mean and rounding tests.
use std::cmp::Ordering;

pub(crate) struct PythonMean;

impl PythonMean {
    /// Divide the exact sum by n before the single binary64 rounding step.
    pub(crate) fn calculate(values: &[f64]) -> Option<f64> {
        if values.is_empty() || values.len() > 1_048_576 {
            return None;
        }
        let mut sum = Magnitude(Vec::new());
        let mut negative = false;
        for &value in values {
            if !value.is_finite() {
                return None;
            }
            if value == 0.0 {
                continue;
            }
            let mut term = Magnitude::from_float(value);
            let sign = value.is_sign_negative();
            if negative == sign {
                sum.add(&term);
            } else {
                match sum.compare(&term) {
                    Ordering::Greater | Ordering::Equal => sum.subtract(&term),
                    Ordering::Less => {
                        term.subtract(&sum);
                        sum = term;
                        negative = sign;
                    }
                }
            }
            if sum.0.is_empty() {
                negative = false;
            }
        }
        sum.round_mean(values.len() as u64, negative)
    }
}

// A nonnegative integer in units of the smallest binary64 subnormal, 2^-1074.
// The bounded input count needs at most 34 limbs; Vec avoids truncation assumptions.
struct Magnitude(Vec<u64>);

impl Magnitude {
    fn from_float(value: f64) -> Self {
        let bits = value.to_bits();
        let exponent = ((bits >> 52) & 0x7ff) as usize;
        let fraction = bits & ((1 << 52) - 1);
        let mantissa = if exponent == 0 {
            fraction
        } else {
            fraction | (1 << 52)
        };
        let shift = exponent.saturating_sub(1);
        let (index, offset) = (shift / 64, shift % 64);
        let mut words = vec![0; index + 2];
        words[index] = mantissa << offset;
        if offset != 0 {
            words[index + 1] = mantissa >> (64 - offset);
        }
        let mut value = Self(words);
        value.normalize();
        value
    }

    fn normalize(&mut self) {
        while self.0.last() == Some(&0) {
            self.0.pop();
        }
    }

    fn compare(&self, other: &Self) -> Ordering {
        self.0
            .len()
            .cmp(&other.0.len())
            .then_with(|| self.0.iter().rev().cmp(other.0.iter().rev()))
    }

    fn add(&mut self, other: &Self) {
        self.0.resize(self.0.len().max(other.0.len()), 0);
        let mut carry = 0u128;
        for (index, word) in self.0.iter_mut().enumerate() {
            let total = *word as u128 + other.0.get(index).copied().unwrap_or(0) as u128 + carry;
            *word = total as u64;
            carry = total >> 64;
        }
        if carry != 0 {
            self.0.push(carry as u64);
        }
    }

    fn subtract(&mut self, other: &Self) {
        debug_assert!(self.compare(other) != Ordering::Less);
        let mut borrow = false;
        for (index, word) in self.0.iter_mut().enumerate() {
            let (partial, first) = word.overflowing_sub(other.0.get(index).copied().unwrap_or(0));
            let (difference, second) = partial.overflowing_sub(u64::from(borrow));
            *word = difference;
            borrow = first || second;
        }
        debug_assert!(!borrow);
        self.normalize();
    }

    fn divide(&mut self, denominator: u64) -> u64 {
        let mut remainder = 0u128;
        for word in self.0.iter_mut().rev() {
            let dividend = (remainder << 64) | *word as u128;
            *word = (dividend / denominator as u128) as u64;
            remainder = dividend % denominator as u128;
        }
        self.normalize();
        remainder as u64
    }

    fn bit(&self, index: usize) -> bool {
        self.0
            .get(index / 64)
            .is_some_and(|word| word & (1 << (index % 64)) != 0)
    }

    fn any_below(&self, boundary: usize) -> bool {
        let (whole, rest) = (boundary / 64, boundary % 64);
        self.0.iter().take(whole).any(|word| *word != 0)
            || (rest != 0
                && self
                    .0
                    .get(whole)
                    .is_some_and(|word| word & ((1 << rest) - 1) != 0))
    }

    fn shifted_word(&self, shift: usize) -> u64 {
        let (index, offset) = (shift / 64, shift % 64);
        let mut word = self.0.get(index).copied().unwrap_or(0) >> offset;
        if offset != 0 {
            word |= self.0.get(index + 1).copied().unwrap_or(0) << (64 - offset);
        }
        word
    }

    fn round_mean(mut self, denominator: u64, negative: bool) -> Option<f64> {
        let remainder = self.divide(denominator);
        let bits = self.0.last().map_or(0, |last| {
            (self.0.len() - 1) * 64 + 64 - last.leading_zeros() as usize
        });
        let mut shift = bits.saturating_sub(53);
        let mut leading = self.shifted_word(shift);
        let up = if shift == 0 {
            let twice = remainder as u128 * 2;
            twice > denominator as u128 || (twice == denominator as u128 && leading & 1 != 0)
        } else {
            self.bit(shift - 1) && (self.any_below(shift - 1) || remainder != 0 || leading & 1 != 0)
        };
        leading += u64::from(up);
        let sign = if negative { 1u64 << 63 } else { 0 };
        if bits <= 52 {
            // Rounding the largest subnormal can carry directly into the first normal.
            return Some(f64::from_bits(sign | leading));
        }
        if leading == 1 << 53 {
            leading >>= 1;
            shift += 1;
        }
        let exponent = shift + 1;
        if exponent >= 0x7ff {
            return None;
        }
        Some(f64::from_bits(
            sign | ((exponent as u64) << 52) | (leading & ((1 << 52) - 1)),
        ))
    }
}

#[cfg(test)]
#[path = "python_mean_tests.rs"]
mod tests;
