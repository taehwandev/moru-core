use super::PythonMean;

fn assert_mean(values: &[f64], expected_bits: u64) {
    assert_eq!(
        PythonMean::calculate(values).map(f64::to_bits),
        Some(expected_bits),
        "{values:?}"
    );
}

#[test]
fn exact_cancellation_and_order_do_not_lose_a_small_term() {
    for values in [[1e16, 1.0, -1e16], [-1e16, 1e16, 1.0], [1.0, -1e16, 1e16]] {
        assert_mean(&values, 0x3fd5_5555_5555_5555);
    }
    assert_mean(&[-1e16, -1.0, 1e16], 0xbfd5_5555_5555_5555);
}

#[test]
fn division_precedes_rounding_and_avoids_fsum_double_rounding() {
    // statistics.mean gives ...556; math.fsum(values)/3 gives ...555.
    assert_mean(&[1.0, 1.0, 1e-16], 0x3fe5_5555_5555_5556);
    assert_mean(&[-1.0, -1.0, -1e-16], 0xbfe5_5555_5555_5556);
}

#[test]
fn finite_means_do_not_overflow_an_intermediate_sum() {
    assert_mean(&[f64::MAX, f64::MAX], f64::MAX.to_bits());
    assert_mean(&[-f64::MAX, -f64::MAX], (-f64::MAX).to_bits());
    assert_mean(&[f64::MAX, f64::MAX, -f64::MAX], 0x7fd5_5555_5555_5555);
}

#[test]
fn ties_round_to_even_for_normal_values() {
    let one = f64::from_bits(0x3ff0_0000_0000_0000);
    let next = f64::from_bits(0x3ff0_0000_0000_0001);
    let after = f64::from_bits(0x3ff0_0000_0000_0002);
    assert_mean(&[one, next], one.to_bits());
    assert_mean(&[next, after], after.to_bits());
}

#[test]
fn subnormal_ties_and_negative_underflow_preserve_sign() {
    let tiny = f64::from_bits(1);
    assert_mean(&[tiny, 0.0], 0);
    assert_mean(&[-tiny, 0.0], 1 << 63);
    assert_mean(&[tiny, tiny, 0.0], 1);
    assert_mean(&[tiny, tiny * 2.0], 2);
    assert_mean(&[f64::from_bits((1 << 52) - 1), f64::MIN_POSITIVE], 1 << 52);
}

#[test]
fn exact_zero_is_positive_even_for_all_negative_zero_inputs() {
    assert_mean(&[-0.0, -0.0], 0);
    assert_mean(&[1.0, -1.0], 0);
    assert_mean(&[-f64::from_bits(1), f64::from_bits(1)], 0);
}

#[test]
fn singleton_finite_values_survive_bit_for_bit() {
    for bits in [
        1,
        1 << 52,
        0x3ff0_0000_0000_0001,
        0x7fef_ffff_ffff_ffff,
        0x8000_0000_0000_0001,
        0xffef_ffff_ffff_ffff,
    ] {
        assert_mean(&[f64::from_bits(bits)], bits);
    }
}

#[test]
fn empty_and_nonfinite_inputs_decline() {
    assert_eq!(PythonMean::calculate(&[]), None);
    for value in [f64::NAN, f64::INFINITY, f64::NEG_INFINITY] {
        assert_eq!(PythonMean::calculate(&[0.0, value]), None);
    }
}
