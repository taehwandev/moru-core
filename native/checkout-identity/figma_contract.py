"""Bind native Figma numeric sums to the build interpreter's observed algorithm.

Owner: Figma sum contract. Imports: stdlib only. No runtime Python, network or
project imports. Verification: observed sum probes plus independent numeric model.
CPython source: Python/bltinmodule.c, builtin_sum_impl and CompensatedSum helpers.
"""
import argparse
import ctypes
import math
from pathlib import Path


def _model(values, profile, bits):
    result, low, fast, floating = 0, 0.0, True, False
    limit = 1 << (bits - 1)

    def finish():
        return result + low if low and math.isfinite(low) else result

    for item in values:
        if not floating and isinstance(item, int):
            total = result + item
            fast = fast and -limit <= item < limit and -limit <= total < limit
            result = total
            continue
        if not floating:
            result = float(result) + item
            floating = True
            continue
        value = float(item)
        if not fast or profile == "sequential":
            result += value
        elif profile == "float_compensated" and isinstance(item, int):
            if -limit <= item < limit:
                result += value
            else:
                result = finish() + value
                low, fast = 0.0, False
        else:
            total = result + value
            low += ((result - total) + value if abs(result) >= abs(value)
                    else (value - total) + result)
            result = total
    return finish() if floating else result


def _outcome(function, values):
    try:
        value = function(values)
        return ("float", value.hex()) if isinstance(value, float) else ("int", str(value))
    except OverflowError:
        return ("overflow",)


def emit(output):
    observed = (sum([1e16, 1.0, -1e16]), sum([1e16, 1, -1e16]))
    profiles = {(0.0, 0.0): "sequential", (1.0, 0.0): "float_compensated",
                (1.0, 1.0): "all_compensated"}
    if observed not in profiles:
        raise RuntimeError("unsupported Python sum algorithm")
    profile = profiles[observed]
    bits = ctypes.sizeof(ctypes.c_long) * 8
    if bits not in (32, 64):
        raise RuntimeError("unsupported Python long width")
    big = 1 << (bits - 1)
    cases = [[], [1, 2], [-0.0], [0.1] * 10, [1e16, 1.0, -1e16],
             [1e16, 1, -1e16], [big, -big, 1e16, 1.0, -1e16],
             [big - 1, 1, -big, 1e16, 1.0, -1e16],
             [1e16, 1.0, big, -big, -1e16], [0.5, 10**100, 1.0],
             [float("inf")], [float("inf"), -float("inf")],
             [float("nan"), 2], [1e308, 1e308, -1e308],
             [1e16, 1.0, 10**400], [10**400, -10**400, 1.5],
             [10**400, 1.5], [5e-324, 5e-324, -5e-324]]
    for values in cases:
        if _outcome(sum, values) != _outcome(lambda v: _model(v, profile, bits), values):
            raise RuntimeError("Python sum profile differs at numeric boundary")
    output.write_text(f'const SUM_PROFILE: &str = "{profile}";\n'
                      f'const SUM_LONG_BITS: u32 = {bits};\n')


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emit", type=Path, required=True)
    emit(parser.parse_args().emit)
