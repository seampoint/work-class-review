#!/usr/bin/env python3
"""Regenerate every draft-3 case and its development indexes in dependency order."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

from corpus_common import CASES, CONFORMANCE, EXPECTED_JUDGMENTS, candidate_pin
from candidate_pin_preflight import inspect_corpus


HERE = Path(__file__).resolve().parent
EXCLUDED_BUILDERS = {
    "build-case-corpus.py",
    "build-case-index.py",
    "build-contract-manifest.py",
    "build-contract-requirements.py",
    "build-contract-schemas.py",
    "build-expectation-review-delta.py",
    "build-expectation-review-packet.py",
    "build-judgment-case-register.py",
    # Review packets and dated correction records bound to an earlier pin; they build no case.
    "build-exact-vector-closure-batch-1.py",
    "build-prior-binding-runtime-judgment-delta.py",
    "build-morning-vector-packet.py",
    "build-prior-binding-current-packet.py",
}
LATE_BUILDERS = {
    "build-equipment-retained-evidence-cases.py",
    # This builder copies cases emitted by branch-routes, dependency-disputes,
    # nested-parallel-closure and restart-admission-controls.
    "build-amendment-batch-controls.py",
    "build-repair-round-effect-controls.py",
    "build-restart-admission-controls.py",
    "build-morning-vector-batch.py",
}

# These dependencies are on materialized source cases, not merely Python imports.
# In particular, replay must follow the disposition it copies at every new pin.
BUILDER_DEPENDENCIES = {
    "build-phase3-closeout-replay-cases.py": {"build-phase3-dispose-closeout-cases.py"},
    "build-timing-admission-cases.py": {"build-sepsis-timing-cases.py"},
    "build-amendment-batch-controls.py": {"build-restart-admission-controls.py"},
}


def case_builders() -> list[Path]:
    builders = {path.name: path for path in sorted(HERE.glob("build-*.py"))
                if path.name not in EXCLUDED_BUILDERS
                and ("CASES /" in path.read_text() or path.name in LATE_BUILDERS)}
    ordinary = set(builders) - LATE_BUILDERS
    dependencies = {name: set(BUILDER_DEPENDENCIES.get(name, set()))
                    | (ordinary if name in LATE_BUILDERS else set()) for name in builders}
    unknown = set().union(*dependencies.values()) - set(builders)
    if unknown:
        raise ValueError(f"missing case-builder dependencies: {sorted(unknown)}")
    ordered, done = [], set()
    while len(done) != len(builders):
        ready = sorted(name for name in builders if name not in done and dependencies[name] <= done)
        if not ready:
            raise ValueError(f"case-builder dependency cycle: {sorted(set(builders)-done)}")
        name = ready[0]
        ordered.append(builders[name]); done.add(name)
    return ordered


def verify_constructor_pins(builders: list[Path], pin: str) -> None:
    # Explicit source-constructor guards require an intentional re-pin. Detect
    # them before any fixture mutation, rather than halfway through the corpus.
    for path in builders:
        for statement in ast.parse(path.read_text(), filename=str(path)).body:
            if (isinstance(statement, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == "EXPECTED_PIN"
                            for target in statement.targets)
                    and isinstance(statement.value, ast.Constant)
                    and statement.value.value != pin):
                raise ValueError(f"refresh explicit EXPECTED_PIN in {path.name} for the selected candidate")


def verify_materialized_prerequisites() -> None:
    # These case builders copy existing source-derived bytes. Building specimens
    # after the cases silently preserves the old pin, even when the index is new.
    pin = candidate_pin()
    verify_constructor_pins(case_builders(), pin)
    for name in ("access-card", "supplier-payment-recovery", "sepsis-surveillance-timing"):
        index = CONFORMANCE / "specimens" / name / "artifact-index.json"
        if json.loads(index.read_text()).get("candidate_pin") != pin:
            raise ValueError(f"regenerate source-derived {name} specimen before the case corpus")


def run(path: Path) -> None:
    print(f"BUILD {path.name}", flush=True)
    subprocess.run([sys.executable, str(path)], cwd=HERE, check=True)


def verify_complete() -> dict[str, object]:
    expected = json.loads(EXPECTED_JUDGMENTS.read_text())
    expected_ids = {row["id"] for row in expected["judgments"] if row["operation"] != "boundary"}
    register = json.loads((HERE / "JUDGMENT-CASE-REGISTER.json").read_text())
    pending_ids = {row["judgment_id"] for row in register["rows"] if not row.get("case_path")}
    expected_ids -= pending_ids
    case_paths: dict[str, Path] = {}
    pin = candidate_pin()
    for path in sorted(CASES.rglob("D2-*.json")):
        case = json.loads(path.read_text())
        case_id = case["id"]
        if case_id in case_paths:
            raise ValueError(f"duplicate case id {case_id}: {case_paths[case_id]} and {path}")
        case_paths[case_id] = path
    missing = sorted(expected_ids - set(case_paths))
    unexpected = sorted(set(case_paths) - {row["id"] for row in expected["judgments"]})
    currency = inspect_corpus(CASES, pin)
    if missing or unexpected or currency["status"] != "PASS":
        raise ValueError(
            json.dumps(
                {"missing": missing, "unexpected": unexpected, "pin_errors": currency["failures"]},
                indent=2,
            )
        )
    return {"candidate_pin": pin, "case_count": str(currency["case_count"]), "builders": str(len(case_builders()))}


def main() -> None:
    verify_materialized_prerequisites()
    for builder in case_builders():
        run(builder)
    run(HERE / "build-case-index.py")
    run(HERE / "build-judgment-case-register.py")
    print(json.dumps(verify_complete(), indent=2))


if __name__ == "__main__":
    main()
