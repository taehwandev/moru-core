"""Observe fused normalization against the original Python startup contract."""
from datetime import date
import os
from pathlib import Path
import random
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import agent_project_memory_consolidate as source
from native_pretool_support import environment, prepare
from support.native_memory_startup import NativeMemoryStartup
from support.native_memory_upkeep import NativeMemoryUpkeep
from support.native_probe_transport import NativeProbe

TODAY = date(2026, 11, 13)


def record(name="a", **values):
    return {"id": name, "status": "active", "body": "한글! Body", "scope": "task",
            "source": "Docs!", "review_on": "2099-01-01", **values}


class StartupSelectionContractTests(unittest.TestCase):
    def test_full_status_packet_omits_inactive_values_and_preserves_input(self):
        marker = object()
        rows = [record("a"), {"status":"retired","body":marker,"replaces":marker},
                record("b",status="pending")]
        counts = {"expired":0,"exact_duplicates":1,"shared_source":1,"unfinished":0}
        def request(operation, packet, **fields):
            self.assertEqual("upkeep-startup-text",operation)
            self.assertEqual(sorted(source.RECALLABLE_STATUSES),fields["statuses"])
            self.assertEqual(["active","retired","pending"],[r["status"] for r in packet])
            self.assertEqual({"id":None,"status":"retired","body":None,"scope":None,
                              "source":None,"review":None,"replaces":None},packet[1])
            return {"counts":counts}
        with patch.object(NativeProbe,"available",return_value=True), \
             patch.object(NativeMemoryUpkeep,"_request",side_effect=request) as probe:
            self.assertEqual(counts,NativeMemoryStartup.hints(rows,TODAY,source.RECALLABLE_STATUSES))
        self.assertIs(marker,rows[1]["body"])
        self.assertEqual(1,probe.call_count)

    def test_counts_remain_bounded_by_live_admission_not_total_rows(self):
        rows = [record("a"),{"status":"retired"},{"status":"retired"}]
        with patch.object(NativeProbe,"available",return_value=True), \
             patch.object(NativeMemoryUpkeep,"_request",return_value={"counts":{
                 "expired":2,"exact_duplicates":0,"shared_source":0,"unfinished":0}}) as probe:
            self.assertIsNone(NativeMemoryStartup.hints(rows,TODAY,source.RECALLABLE_STATUSES))
        self.assertEqual(1,probe.call_count)


class NativeMemoryStartupTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="native-startup-text-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.entry, self.project = prepare(self.base)
        empty = self.base / "empty"
        empty.mkdir()
        self.env = {**environment(self.base), "PATH": str(empty)}

    def run_startup(self, rows):
        with patch.dict(os.environ, self.env, clear=True):
            return source.startup_summary_line(rows, self.project, "moru-hook", today=TODAY)

    def reference(self, rows):
        return source._startup_summary_line_reference(rows, self.project, "moru-hook", today=TODAY)

    def test_real_notice_rendering_skips_python_counts_format_with_legacy_negative_control(self):
        rows = [record("a",review_on="2026-11-13"),record("b",replaces="a")]
        prefix = "Project memory upkeep: expired=1 exact_duplicates=1 shared_source=1 unfinished=1"
        command = source.shlex.join(["moru-hook","project-memory","--project",str(self.project),"consolidate"])
        expected = prefix+" -> "+command
        calls = []
        code = source._summary_counts_line.__code__
        def observe(frame,event,arg):
            if event == "call" and frame.f_code is code:calls.append(True)
        previous = sys.getprofile()
        with patch.object(NativeProbe,"request",wraps=NativeProbe.request) as requested:
            try:
                sys.setprofile(observe)
                actual = self.run_startup(rows)
            finally:sys.setprofile(previous)
        self.assertEqual(expected,actual)
        self.assertEqual([],calls,"Python count-notice formatting replay")
        self.assertEqual(1,requested.call_count)
        original = NativeMemoryStartup.hints
        def legacy(rows,today,statuses):return original(rows,today,statuses)
        with patch.object(NativeMemoryStartup,"hints",legacy):
            try:
                sys.setprofile(observe)
                self.assertEqual(expected,self.run_startup(rows))
            finally:sys.setprofile(previous)
        self.assertEqual([True],calls)

    def test_legacy_count_reply_reuses_the_counts_without_another_request(self):
        rows = [record("a"),record("b")]
        counts = {"expired":1,"exact_duplicates":0,"shared_source":0,"unfinished":0}
        expected = source._summary_counts_line(counts,self.project,"moru-hook")
        with patch.object(NativeProbe,"request",return_value={"counts":counts}) as requested, \
             patch.object(source,"_startup_summary_line_reference",side_effect=AssertionError("count replay")):
            self.assertEqual(expected,self.run_startup(rows))
        self.assertTrue(requested.call_args.args[2]["render"])
        self.assertEqual(1,requested.call_count)

    def test_custom_formatter_is_preserved_even_for_empty_or_zero_counts(self):
        for rows in ([],[record("a")],[record("a"),record("b")]):
            with self.subTest(rows=len(rows)),patch.object(source,"_summary_counts_line",return_value="custom notice") as formatted, \
                 patch.object(NativeProbe,"request",wraps=NativeProbe.request) as requested:
                self.assertEqual("custom notice",self.run_startup(rows))
                self.assertEqual(1,formatted.call_count)
                if requested.call_count:self.assertNotIn("render",requested.call_args.args[2])

    def test_formatter_changed_during_request_is_rechecked_without_count_replay(self):
        rows = [record("a"),record("b")]
        original_request, original_summary = NativeProbe.request, source._summary_counts_line
        def request(*args,**kwargs):
            result = original_request(*args,**kwargs)
            source._summary_counts_line = lambda *args:"late custom notice"
            return result
        with patch.object(NativeProbe,"request",side_effect=request) as requested:
            try:self.assertEqual("late custom notice",self.run_startup(rows))
            finally:source._summary_counts_line = original_summary
        self.assertEqual(1,requested.call_count)

    def test_custom_request_signature_and_in_place_code_keep_legacy_counts(self):
        rows = [record("a"),record("b")]
        counts = {"expired":1,"exact_duplicates":0,"shared_source":0,"unfinished":0}
        expected = source._summary_counts_line(counts,self.project,"moru-hook")
        def request(operation,rows,*,today,statuses):return {"counts":counts}
        with patch.object(NativeMemoryUpkeep,"_request",request):
            self.assertEqual(expected,self.run_startup(rows))
        original = NativeMemoryUpkeep._request.__code__
        def altered(operation,rows,**fields):
            assert "render" not in fields
            return {"counts":{"expired":1,"exact_duplicates":0,"shared_source":0,"unfinished":0}}
        try:
            NativeMemoryUpkeep._request.__code__ = altered.__code__
            self.assertEqual(expected,self.run_startup(rows))
        finally:NativeMemoryUpkeep._request.__code__ = original

    def test_malformed_rendering_or_counts_uses_one_attempt_then_original_notice(self):
        rows = [record("a"),record("b")]
        counts = {"expired":0,"exact_duplicates":1,"shared_source":1,"unfinished":0}
        prefix = "Project memory upkeep: expired=0 exact_duplicates=1 shared_source=1 unfinished=0"
        replies = [{"counts":counts,"text":text} for text in (None,True,"","X"*201,"other notice",prefix+"\n",prefix+"한글")]
        replies += [{"counts":{**counts,"expired":value},"text":prefix} for value in (True,-1,3)]
        replies += [{"counts":counts,"text":prefix,"extra":True},
                    {"counts":dict.fromkeys(counts,0),"text":prefix}]
        expected = self.reference(rows)
        for reply in replies:
            with self.subTest(reply=reply),patch.object(NativeProbe,"request",return_value=reply) as requested, \
                 patch.object(source,"_startup_summary_line_reference",wraps=source._startup_summary_line_reference) as reference:
                self.assertEqual(expected,self.run_startup(rows))
                self.assertEqual(1,requested.call_count)
                self.assertEqual(1,reference.call_count)

    def test_silent_notice_never_stringifies_project_or_launcher(self):
        class Opaque:
            def __str__(self):raise AssertionError("silent notice stringified a command argument")
        with patch.dict(os.environ,self.env,clear=True):
            for rows in ([],[{"status":"retired"}],[record("a")]):
                with self.subTest(rows=len(rows)),patch.object(source,"_summary_command",side_effect=AssertionError("silent command")):
                    self.assertEqual("",source.startup_summary_line(rows,Opaque(),Opaque(),today=TODAY))

    def test_native_notice_keeps_python_quoting_and_custom_command_callbacks(self):
        rows = [record("a"),record("b")]
        launchers = ("moru-hook","./my tool's $name","tool\nline","")
        project = Path("space ' 한글/$value")
        for launcher in launchers:
            expected = source._startup_summary_line_reference(rows,project,launcher,today=TODAY)
            with self.subTest(launcher=launcher),patch.dict(os.environ,self.env,clear=True):
                actual = source.startup_summary_line(rows,project,launcher,today=TODAY)
                self.assertEqual(expected,actual)
                self.assertEqual([launcher,"project-memory","--project",str(project),"consolidate"],
                                 source.shlex.split(actual.split(" -> ",1)[1]))
        with patch.object(source.shlex,"join",return_value="custom command") as joined:
            self.assertTrue(self.run_startup(rows).endswith(" -> custom command"))
            self.assertEqual(1,joined.call_count)

    def test_request_customization_before_lazy_startup_import_keeps_its_signature(self):
        program = """
from datetime import date
from pathlib import Path
import agent_project_memory_consolidate as source
from support.native_memory_upkeep import NativeMemoryUpkeep
from support.native_probe_transport import NativeProbe
NativeProbe.available = staticmethod(lambda: True)
def custom(operation,rows,*,today,statuses):
    return {"counts":{"expired":1,"exact_duplicates":0,"shared_source":0,"unfinished":0}}
NativeMemoryUpkeep._request = custom
rows = [{"id":"a","status":"active","body":"x","scope":"task","source":"s","review_on":"2099-01-01"}]
assert "expired=1" in source.startup_summary_line(rows,Path("."),"moru-hook",today=date(2026,11,13))
"""
        env = {**self.env,"PYTHONPATH":str(Path(source.__file__).parent)}
        done = subprocess.run([sys.executable,"-B","-c",program],env=env,cwd=self.base,
                              capture_output=True,text=True,timeout=8)
        self.assertEqual(0,done.returncode,done.stderr)

    def test_render_flag_requires_a_plain_boolean_before_transport(self):
        with patch.object(NativeProbe,"request",side_effect=AssertionError("unexpected request")):
            for value in (None,1,"true",[]):
                self.assertIsNone(NativeMemoryStartup.hints([record()],TODAY,source.RECALLABLE_STATUSES,render=value))

    def test_fused_request_skips_python_normalization_and_date_parsing(self):
        marker = object()
        rows = [record("a", review_on="2026-11-13", opaque=marker), record("b", replaces="a")]
        before = [dict(r) for r in rows]
        expected = self.reference(rows)
        normalizer = source.normalize.__code__
        calls = []
        def observe(frame, event, function):
            if event == "call" and frame.f_code is normalizer:
                calls.append("normalize")
            if event == "c_call" and getattr(function, "__name__", "") in ("fromisoformat", "toordinal"):
                calls.append(function.__name__)
        previous = sys.getprofile()
        with patch.object(source, "_startup_summary_line_reference", side_effect=AssertionError("Python replay")), \
             patch.object(NativeMemoryUpkeep, "_request", wraps=NativeMemoryUpkeep._request) as requested:
            try:
                sys.setprofile(observe)
                actual = self.run_startup(rows)
            finally:
                sys.setprofile(previous)
        self.assertEqual(expected, actual)
        self.assertEqual([], calls)
        self.assertEqual(1, requested.call_count)
        self.assertEqual("upkeep-startup-text", requested.call_args.args[0])
        self.assertEqual(rows[0]["body"], requested.call_args.args[1][0]["body"])
        self.assertEqual(before, rows)
        self.assertIs(marker, rows[0]["opaque"])

    def test_unicode_case_punctuation_and_whitespace_notices_match_reference(self):
        texts = ["Straße", "STRASSE", "İ", "I", "ΟΣ", "ΟΣΑ", "Σ", "AΣ\u0301", "AΣ\u0301B",
                 "AΣ'B", "AΣ\u200dB", "ᵃΣ", "AᵃΣ", "A\u001cB\u0085C", "A-B", "A B",
                 "foo_bar", "e\u0301", "É", "!!!", "Ⅰ²０", "한글! 본문?", "\0", "𐐀𐐁"]
        for text in texts:
            rows = [record("a", body=text, source=text),
                    record("b", body=source.normalize(text), source=source.normalize(text), scope="all")]
            expected = self.reference(rows)
            with patch.object(source, "_startup_summary_line_reference", side_effect=AssertionError("Python replay")):
                self.assertEqual(expected, self.run_startup(rows), repr(text))
        for first, second in (("Straße", "STRASSE"), ("A-B", "A B"), ("foo_bar", "foobar")):
            rows = [record("a", body=first), record("b", body=second)]
            self.assertEqual(self.reference(rows), self.run_startup(rows))

    def test_sampled_lowercase_and_sigma_contexts_match_builder_interpreter(self):
        rng = random.Random(61114)
        candidates = [chr(cp) for cp in range(0x110000)
                      if chr(cp).lower() != chr(cp) or chr(cp).isspace()]
        texts = ["A" + c + "Σ" for c in rng.sample(candidates, 128)]
        texts += ["AΣ" + c + "B" for c in ("\u0301", "\u0345", "\u200d", "ᵃ", "'", ".", "\u001c")]
        for start in range(0, len(texts), 32):
            rows = [record(str(i), body=text, source=text) for i, text in enumerate(texts[start:start+32])]
            expected = self.reference(rows)
            with patch.object(source, "_startup_summary_line_reference", side_effect=AssertionError("Python replay")):
                self.assertEqual(expected, self.run_startup(rows))

    def test_seeded_scope_status_and_link_groups_match_reference(self):
        rng = random.Random(214)
        for _ in range(8):
            rows = [record(str(i % 5), body=rng.choice(["Same!", "SAME", "", "Ος", "ΟΣ", "한글"]),
                source=rng.choice(["Docs!", " docs ", "", "!?", "출처"]), scope=rng.choice(["task", "review", "all"]),
                status=rng.choice(["active", "pending", "approved", "retired", "ACTIVE"]), replaces=rng.choice([None, "", "1"]),
                review_on=rng.choice(["0001-01-01", "2026-11-13", "9999-12-31"])) for i in range(37)]
            expected = self.reference(rows)
            with patch.object(source, "_startup_summary_line_reference", side_effect=AssertionError("Python replay")):
                self.assertEqual(expected, self.run_startup(rows))

    def test_mixed_statuses_use_one_native_request_and_detect_missing_selection(self):
        rows = [record("a",review_on="2026-11-13"),record("b",replaces="a"),
                {"status":"retired","body":object(),"review_on":object(),"replaces":object()}]
        expected = self.reference(rows)
        with patch.object(source,"_startup_summary_line_reference",side_effect=AssertionError("Python selection replay")), \
             patch.object(NativeMemoryUpkeep,"_request",wraps=NativeMemoryUpkeep._request) as probe:
            self.assertEqual(expected,self.run_startup(rows))
        self.assertEqual(1,probe.call_count)
        self.assertEqual(3,len(probe.call_args.args[1]))
        self.assertEqual(sorted(source.RECALLABLE_STATUSES),probe.call_args.kwargs["statuses"])
        request = NativeMemoryUpkeep._request
        def without_selection(operation, packet, **fields):
            fields.pop("statuses",None)
            return request(operation,packet,**fields)
        with patch.object(NativeMemoryUpkeep,"_request",side_effect=without_selection), \
             patch.object(source,"_startup_summary_line_reference",side_effect=AssertionError("Python selection replay")):
            with self.assertRaisesRegex(AssertionError,"Python selection replay"):
                self.run_startup(rows)

    def test_decline_and_invalid_packets_normalize_each_field_once(self):
        rows = [record("a"), record("b", replaces="a")]
        expected = self.reference(rows)
        code = source.normalize.__code__
        for packet in (None, {}, {"counts":None}, {"counts":{"expired":True}},
                       {"counts":dict.fromkeys(("expired","exact_duplicates","shared_source","unfinished"),3)}):
            calls = []
            def observe(frame, event, function):
                if event == "call" and frame.f_code is code:
                    calls.append(1)
            previous = sys.getprofile()
            with patch.object(NativeProbe, "request", return_value=packet):
                try:
                    sys.setprofile(observe)
                    self.assertEqual(expected, self.run_startup(rows))
                finally:
                    sys.setprofile(previous)
            self.assertEqual(2 * len(rows), len(calls))

    def test_custom_normalizer_and_regex_bindings_keep_python_callbacks(self):
        rows = [record("a", body="Alpha1"), record("b", body="Alpha2")]
        with patch.object(source, "normalize", wraps=source.normalize) as normalized, \
             patch.object(NativeMemoryStartup, "hints", side_effect=AssertionError("custom bypass")):
            expected = self.reference(rows)
            normalized.reset_mock()
            self.assertEqual(expected, self.run_startup(rows))
            self.assertEqual(2 * len(rows), normalized.call_count)
        with patch.object(source, "_PUNCTUATION_RE", re.compile("[^a-z]")), \
             patch.object(NativeMemoryStartup, "hints", side_effect=AssertionError("regex bypass")):
            self.assertEqual(self.reference(rows), self.run_startup(rows))

    def test_in_place_normalizer_code_override_is_not_bypassed(self):
        rows = [record("a", body="first"), record("b", body="second")]
        def altered(text):
            return "same"
        original_code = source.normalize.__code__
        try:
            source.normalize.__code__ = altered.__code__
            with patch.object(NativeMemoryStartup, "hints", side_effect=AssertionError("code bypass")):
                self.assertEqual(self.reference(rows), self.run_startup(rows))
        finally:
            source.normalize.__code__ = original_code

    def test_unavailable_empty_and_retired_profiles_do_not_request_transport(self):
        rows = [record("a")]
        expected = self.reference(rows)
        with patch.object(NativeProbe, "available", return_value=False), \
             patch.object(NativeProbe, "request", side_effect=AssertionError("unavailable request")):
            self.assertEqual(expected, self.run_startup(rows))
        with patch.object(NativeProbe, "request", side_effect=AssertionError("empty request")):
            self.assertEqual("", self.run_startup([]))
            self.assertEqual("", self.run_startup([{"status":"retired","body":None,"review_on":"bad"}]))

    def test_surrogates_malformed_profiles_and_date_errors_keep_reference(self):
        for rows in ([record(body="A\ud800B")], [record(review_on="1900-02-29")],
                     [record(replaces=[])], [{}], [record(status=[])]):
            try:
                expected = self.reference(rows)
            except Exception as error:
                with self.assertRaises(type(error)) as actual:
                    self.run_startup(rows)
                self.assertEqual(error.args, actual.exception.args)
            else:
                self.assertEqual(expected, self.run_startup(rows))

    def test_public_native_wiring_has_a_negative_control(self):
        rows = [record("a"), record("b")]
        expected = self.reference(rows)
        with patch.object(source, "_startup_summary_line_reference", side_effect=AssertionError("Python replay")):
            self.assertEqual(expected, self.run_startup(rows))
            with patch.object(NativeMemoryStartup, "hints", return_value=None):
                with self.assertRaisesRegex(AssertionError, "Python replay"):
                    self.run_startup(rows)
