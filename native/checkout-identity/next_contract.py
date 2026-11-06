"""Generate read-only next-advice vocabulary from canonical gate owners.

Owner: next-advice build contract; allowed imports: stdlib and gate/template owners.
Forbidden: lifecycle writes or test execution; callers: build.rs; verification: next parity.
"""
import argparse
import itertools
import json
from pathlib import Path
import sys


def emit(output):
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    from agent_finish_gate_learning_validators import CAUSAL_RETROSPECTIVE_FIELDS
    from agent_gate_evidence import FIELD_REQUIREMENTS, gate_field_enums
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
    text = json.dumps(contract, ensure_ascii=False, separators=(",", ":"))
    output.write_text("const CONTRACT: &str = " + json.dumps(text, ensure_ascii=False) + ";\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emit", type=Path, required=True)
    emit(parser.parse_args().emit)
