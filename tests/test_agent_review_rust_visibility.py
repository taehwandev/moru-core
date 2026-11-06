"""Rust declaration visibility must not treat private support types as exports."""
from pathlib import Path
import unittest

from agent_review_purpose import top_level_type_declarations, top_level_declaration_failures


class RustVisibilityTests(unittest.TestCase):
    def declarations(self, text):
        return top_level_type_declarations(Path("src/handler.rs"), text.splitlines())

    def test_private_outcome_with_public_fields_is_not_a_public_owner(self):
        rows = self.declarations("struct Outcome { pub code: i32 }\npub(crate) struct Handler;\n")
        self.assertTrue(rows[0]["private"])
        self.assertFalse(rows[0]["exported"])
        self.assertTrue(rows[1]["exported"])
        self.assertEqual([], top_level_declaration_failures(Path("src/handler.rs"), rows))

    def test_all_explicit_visibility_forms_still_count_as_exported_owners(self):
        for prefix in ("pub", "pub(crate)", "pub(super)", "pub(self)", "pub(in crate::parent)"):
            with self.subTest(prefix=prefix):
                rows = self.declarations(f"{prefix} struct One;\n{prefix} enum Two {{}}\n")
                self.assertEqual(2, len(rows))
                self.assertTrue(all(row["exported"] and not row["private"] for row in rows))
                errors = top_level_declaration_failures(Path("src/handler.rs"), rows)
                self.assertTrue(any("2 public/exported" in error for error in errors))

    def test_private_types_do_not_consume_nonprivate_owner_budget(self):
        rows = self.declarations("\n".join(f"struct Helper{i};" for i in range(6)))
        self.assertEqual([], top_level_declaration_failures(Path("src/handler.rs"), rows))

    def test_restricted_public_functions_and_underscore_types_are_counted(self):
        rows = self.declarations("fn helper() {}\npub(in crate::parent) fn run() {}\npub struct _Visible;\n")
        self.assertEqual(["run", "_Visible"], [row["name"] for row in rows])
        self.assertTrue(all(row["exported"] and not row["private"] for row in rows))
        self.assertTrue(any("2 public/exported" in item for item in top_level_declaration_failures(Path("src/handler.rs"), rows)))

    def test_other_language_public_defaults_are_preserved(self):
        path = Path("Handler.kt")
        rows = top_level_type_declarations(path, ["class One {}", "class Two {}"])
        self.assertTrue(any("2 public/exported" in item for item in top_level_declaration_failures(path, rows)))


if __name__ == "__main__":
    unittest.main()
