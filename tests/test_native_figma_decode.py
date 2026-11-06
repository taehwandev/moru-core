"""Exact file decoding and JSON diagnostics through the installed native CLI."""
import json
import random
import sys
import unittest

import test_native_figma_validate as fixtures
from native_pretool_support import result


class NativeFigmaDecode(unittest.TestCase):
    setUp = fixtures.NativeFigmaValidate.setUp
    call = fixtures.NativeFigmaValidate.call

    def error_parity(self, content):
        raw = content.encode("utf-8") if isinstance(content, str) else content
        self.summary.write_bytes(raw)
        args = [str(self.summary)]
        expected = self.call(args, backend="python")
        self.assertEqual(2, expected.returncode, expected.stderr)
        self.assertEqual(b"", expected.stdout)
        self.assertEqual(result(expected), result(self.call(args)))
        self.assertEqual(result(expected), result(self.call(args, PATH=str(self.empty_path))))
        self.assertEqual(raw, self.summary.read_bytes())

    def test_json_syntax_diagnostics_and_numeric_prefix_positions(self):
        cases = ["", " ", "\n\r\t", "{", "[", "[1", "[1,", "[1,]", '{"a":1,}',
                 '{"a"}', '{"a" 1}', '{"a":}', '{"a":1 "b":2}', "[,1]", "[1 2]",
                 "{a:1}", "{'a':1}", '"unterminated', '"escape\\', '"bad\\q"',
                 '"\\u"', '"\\u0"', '"\\u000g"', '"\\u12z4"', '"a\x01b"',
                 "tru", "truex", "nul", "false false", "-", "-x", "+1", "01",
                 "1.", "1e", "1e+", ".1", "0e-", "-01", "Infinityx", "NaNx", "-NaN",
                 "\ufeff{}", " \ufeff{}", '"한글😀"x', '{"😀": 1,}', '["한글", ]',
                 '{\r\n"a": [1,\r2,]\r}', '"literal\r\nnewline"', "\n\n[1,,2]"]
        for content in cases:
            with self.subTest(content=repr(content)):
                self.error_parity(content)

    def test_unicode_offset_and_newline_normalization(self):
        for prefix in ("", "\n", "\r", "\r\n", "\r\n\r\n", " \t"):
            for content in ('["😀한글",x]', '{"한글":"😀", "b" x}', '"😀\\z"', '"😀\x00"'):
                with self.subTest(prefix=repr(prefix), content=repr(content)):
                    self.error_parity(prefix + content)
        payload = fixtures._valid_summary()
        original = json.dumps(payload, indent=2).encode()
        for newline in (b"\r", b"\r\n"):
            self.summary.write_bytes(original.replace(b"\n", newline))
            args = [str(self.summary)]
            expected = self.call(args, backend="python")
            self.assertEqual(0, expected.returncode, expected.stderr)
            self.assertEqual(result(expected), result(self.call(args, PATH=str(self.empty_path))))

    def test_deterministic_malformed_mutations_keep_reference_diagnostics(self):
        base = '{"한글😀":[true,false,null,1.25e-3,{"x":"a\\tb"}]}'
        rng = random.Random(7193)
        cases = set()
        for _ in range(120):
            position = rng.randrange(len(base))
            replacement = rng.choice(['"', "}", ",", "\\", "\n", "\x01", "漢", ""])
            candidate = base[:position] + replacement + base[position + 1:]
            try:
                json.loads(candidate)
            except ValueError:
                cases.add(candidate)
        self.assertGreater(len(cases), 40)
        for candidate in sorted(cases):
            with self.subTest(candidate=repr(candidate)):
                self.error_parity(candidate)

    def test_utf8_errors_precede_json_and_keep_byte_positions(self):
        invalid = [b"\x80", b"\xc0\x80", b"\xc1\xbf", b"\xf5\x80\x80\x80", b"\xff",
                   b"\xc2", b"\xc2x", b"\xe0\x80\x80", b"\xed\xa0\x80",
                   b"\xe2", b"\xe2\x82", b"\xe2x\xac", b"\xe2\x82x",
                   b"\xf0\x80\x80\x80", b"\xf4\x90\x80\x80",
                   b"\xf0", b"\xf0\x90", b"\xf0\x90\x80", b"\xf0\x90x\x80",
                   b"\xf0\x90\x80x"]
        for prefix in (b"", b"{", "😀\r\n".encode(), b"\xef\xbb\xbf", b" " * 8191):
            for bad in invalid:
                with self.subTest(prefix=len(prefix), bad=bad):
                    self.error_parity(prefix + bad)

    def test_integer_digit_limit_precedes_later_json_errors(self):
        limit = getattr(sys, "get_int_max_str_digits", lambda: 0)()
        if not limit:
            self.skipTest("builder Python has no integer digit limit")
        for prefix, suffix in (("", ""), ("-", "x"), ('{"a":', ",}"), ("[", ",]")):
            self.error_parity(prefix + "9" * (limit + 1) + suffix)


if __name__ == "__main__":
    unittest.main()
