"""Generate read-only next-advice vocabulary from canonical gate owners.

Owner: next-advice build contract; allowed imports: stdlib and gate/template owners.
Forbidden: lifecycle writes or test execution; callers: build.rs; verification: next parity.
"""
import argparse
import itertools
import json
from pathlib import Path
import sys
import string
import os
import shutil
from unittest.mock import patch


def emit(output):
    print("cargo:rustc-env=MORU_NEXT_ARGPARSE_COLOR="
          + str(bool(getattr(argparse.ArgumentParser(), "color", False))).lower())
    with patch.dict(os.environ, {"COLUMNS": "0", "LINES": "0"}), \
         patch("os.get_terminal_size", return_value=os.terminal_size((0, 0))):
        zero_columns = shutil.get_terminal_size().columns
    if zero_columns not in (0, 80):
        raise RuntimeError("unrecognized zero-column terminal policy")
    print("cargo:rustc-env=MORU_NEXT_ZERO_COLUMNS=" + str(zero_columns))
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    from agent_finish_gate_learning_validators import CAUSAL_RETROSPECTIVE_FIELDS
    from agent_gate_evidence import (FIELD_REQUIREMENTS, gate_field_enums, SCHEMA_VERSION,
        CAPSULE_BINDING_FIELD, PROSE_COMPATIBLE_STRUCTURED_GATES, MULTI_AGENT_SERIAL_MODES,
        MULTI_AGENT_PARALLEL_FIELDS, _GATE_RENDERERS)
    from agent_finish_gate_surface_validators import _LABELS, _EMPTY_VALUES
    from agent_gate_record_template import _placeholder, remaining_gate_template_lines
    from agent_review_hook import GATE_REQUIRED_REVIEW_EVIDENCE, required_review_evidence_flags
    from agent_skill_catalog import SKILL_CONTAINER_DIRS, SKILL_ID_ALIASES
    from agent_start_guidance import review_shape_line

    gates = {}
    for gate in dict.fromkeys([*FIELD_REQUIREMENTS, "review hook", "commit readiness", "retrospective check"]):
        causal = CAUSAL_RETROSPECTIVE_FIELDS if gate == "retrospective check" else ()
        names = dict.fromkeys([*FIELD_REQUIREMENTS.get(gate, ()), *causal])
        enums = gate_field_enums(gate)
        gates[gate] = {
            "fields": {name: _placeholder(gate, name, enums) for name in names},
            "template": remaining_gate_template_lines([gate], [])[1],
        }
    review_gates = list(GATE_REQUIRED_REVIEW_EVIDENCE)
    reviews = []
    for bits in itertools.product((False, True), repeat=len(review_gates)):
        present = [gate for gate, enabled in zip(review_gates, bits) if enabled]
        flags = required_review_evidence_flags(present)
        reviews.append({"gates": present, "flags": flags, "shape": review_shape_line(flags)})
    note = remaining_gate_template_lines(["retrospective check"], ["sample"])[-1]
    contract = {"gates": gates, "reviews": reviews, "review_gates": review_gates,
                "containers": sorted(SKILL_CONTAINER_DIRS), "aliases": SKILL_ID_ALIASES,
                "skills_note": note.removesuffix("sample")}
    expected = {"cycle contract", "agentic run state", "ambiguity check", "alignment brief",
                "boundary plan", "work surface resolution", "multi-agent split decision",
                "side-effect audit", "retrospective check", "documentation impact",
                "documentation", "source docs", "tests"}
    if set(_GATE_RENDERERS) != expected:
        raise RuntimeError("next ledger gate renderer set changed; review native predicates")
    surface_fields = {name: "{" + name + "}" for name in FIELD_REQUIREMENTS["work surface resolution"]}
    surface = _GATE_RENDERERS["work surface resolution"]("work surface resolution", surface_fields, "")[0]
    contract["ledger"] = {
        "schema": SCHEMA_VERSION, "capsule_field": CAPSULE_BINDING_FIELD,
        "required": FIELD_REQUIREMENTS, "prose": sorted(PROSE_COMPATIBLE_STRUCTURED_GATES),
        "renderers": sorted(_GATE_RENDERERS), "serial": sorted(MULTI_AGENT_SERIAL_MODES),
        "parallel_fields": MULTI_AGENT_PARALLEL_FIELDS,
        "closed_fields": {gate: gate_field_enums(gate) for gate in ("ambiguity check", "alignment brief")},
        "surface_template": [[literal, field] for literal, field, _, _ in string.Formatter().parse(surface)],
        "surface_labels": _LABELS, "surface_empty": sorted(_EMPTY_VALUES),
    }
    text = json.dumps(contract, ensure_ascii=False, separators=(",", ":"))
    output.write_text("const CONTRACT: &str = " + json.dumps(text, ensure_ascii=False) + ";\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emit", type=Path, required=True)
    emit(parser.parse_args().emit)
