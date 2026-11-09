#!/usr/bin/env python3
"""Regenerate the draft-3 contract-review requirement inventory."""

from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
LIBRARY = ROOT / "library/work-class-specification/1.0.0-draft.3"
OUTPUT = LIBRARY / "requirements.json"
SOURCE_MAPPING = "conformance/work-class/1.0.0-draft.3/review/SOURCE-COMPATIBILITY.md"


def identified_sections(name: str) -> dict[str, tuple[str, str]]:
    lines = (LIBRARY / name).read_text().splitlines()
    starts: list[tuple[int, str, str]] = []
    for index, line in enumerate(lines):
        match = re.match(r"^## ([A-Z][A-Z0-9-]+)\. (.+)$", line)
        if match:
            starts.append((index, match.group(1), match.group(2)))
    return {
        requirement_id: (title, "\n".join(lines[start + 1 : starts[position + 1][0] if position + 1 < len(starts) else len(lines)]).strip())
        for position, (start, requirement_id, title) in enumerate(starts)
    }


def numbered_sections(name: str) -> dict[str, tuple[str, str]]:
    lines = (LIBRARY / name).read_text().splitlines()
    starts: list[tuple[int, str, str]] = []
    for index, line in enumerate(lines):
        match = re.match(r"^## ([0-9]+)\. (.+)$", line)
        if match:
            starts.append((index, match.group(1), match.group(2)))
    return {
        section: (title, "\n".join(lines[start + 1 : starts[position + 1][0] if position + 1 < len(starts) else len(lines)]).strip())
        for position, (start, section, title) in enumerate(starts)
    }


def plain_sections(name: str) -> dict[str, str]:
    lines = (LIBRARY / name).read_text().splitlines()
    starts = [(index, line[3:]) for index, line in enumerate(lines) if line.startswith("## ")]
    return {
        title: "\n".join(lines[start + 1 : starts[position + 1][0] if position + 1 < len(starts) else len(lines)]).strip()
        for position, (start, title) in enumerate(starts)
    }


def subsection(body: str, title: str) -> str:
    lines = body.splitlines()
    starts = [(index, line[4:]) for index, line in enumerate(lines) if line.startswith("### ")]
    for position, (start, found_title) in enumerate(starts):
        if found_title == title:
            end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
            return "\n".join(lines[start + 1 : end]).strip()
    raise KeyError(title)


def preamble(name: str) -> str:
    lines = (LIBRARY / name).read_text().splitlines()
    first_section = next((index for index, line in enumerate(lines) if line.startswith("## ")), len(lines))
    return "\n".join(lines[1:first_section]).strip()


identified: dict[str, tuple[str, str, str]] = {}
for document in ["AGGREGATES.md", "AUTHORITY.md", "LIFECYCLE.md", "PROTOCOL.md", "Specification.md", "RESERVATIONS.md", "RECOVERY.md", "TIMING.md", "INDEPENDENT-HUMAN-DECISIONS.md", "HOLDINGS.md", "ASSESSMENTS.md", "INFORMATION-FLOW.md"]:
    for requirement_id, (title, body) in identified_sections(document).items():
        identified[requirement_id] = (document, title, body)

composition = numbered_sections("COMPOSITION.md")
authority_checks = plain_sections("AUTHORITY-CHECKS.md")
reservation_records = plain_sections("RESERVATION-RECORDS.md")
scope = plain_sections("SCOPE-AND-BOUNDARY.md")

manual: dict[str, tuple[str, str, str, str, str]] = {
    "SCOPE-001": ("SCOPE-AND-BOUNDARY.md", "Candidate scope", "COMMON", "MIXED", preamble("SCOPE-AND-BOUNDARY.md")),
    "BOUND-001": ("SCOPE-AND-BOUNDARY.md", "Boundary records", "REVIEW_EVIDENCE", "MIXED", scope["Boundary records"]),
    "CLAIM-001": ("SCOPE-AND-BOUNDARY.md", "Roles and claims", "ADAPTER", "MIXED", scope["Roles and claims"]),
    "HOST-003": ("EXTERNAL-DEPENDENCIES.md", "External dependencies and host obligations", "REFERENCE_SINGLE_PROCESS_CONTENTION", "MIXED", preamble("EXTERNAL-DEPENDENCIES.md")),
    "AUTH-007": ("AUTHORITY.md", "General source observations", "AUTHORITY_EVALUATOR", "MECHANICAL", identified["AUTH-007"][2]),
    "AUTH-CHECK-001": ("AUTHORITY-CHECKS.md", "Static definition admission", "AUTHORITY_EVALUATOR", "MECHANICAL", authority_checks["Static definition admission"]),
    "AUTH-CHECK-002": ("AUTHORITY-CHECKS.md", "Record and time admission", "AUTHORITY_EVALUATOR", "MECHANICAL", authority_checks["Record and time admission"]),
    "AUTH-CHECK-003": ("AUTHORITY-CHECKS.md", "Exact successful check construction", "AUTHORITY_EVALUATOR", "MECHANICAL", authority_checks["Exact successful check construction"]),
    "AUTH-CHECK-004": ("AUTHORITY-CHECKS.md", "Deterministic refusal selection", "AUTHORITY_EVALUATOR", "MECHANICAL", authority_checks["Deterministic refusal selection"]),
    "PROF-001": ("COMPOSITION.md", composition["1"][0], "WORK_RUNTIME", "MECHANICAL", composition["1"][1]),
    "WCD-001": ("COMPOSITION.md", composition["2"][0], "WORK_RUNTIME", "MECHANICAL", composition["2"][1]),
    "LINEAR-001": ("COMPOSITION.md", composition["3"][0], "LINEAR_WORK_RUNTIME", "MECHANICAL", composition["3"][1]),
    "LIFE-006A": ("LIFECYCLE.md", "Declared terminal completion and referrals", "LINEAR_WORK_RUNTIME", "MECHANICAL", identified["LIFE-006A"][2]),
    "LIFE-009A": ("LIFECYCLE.md", "Dispatch authorization fence", "LINEAR_WORK_RUNTIME", "MIXED", identified["LIFE-009A"][2]),
    "LIFE-020A": ("SOURCE-CORRECTIONS.md", "External source correction evidence", "REVIEW_EVIDENCE", "MECHANICAL", preamble("SOURCE-CORRECTIONS.md") + "\n\n" + "\n\n".join(title + "\n\n" + body for title, body in numbered_sections("SOURCE-CORRECTIONS.md").values())),
    "COMP-BIND-001": ("COMPOSITION.md", "Prior-effect and actor bindings", "WORK_RUNTIME", "MECHANICAL", subsection(composition["2"][1], "2.3 Prior-effect and actor bindings")),
    "COMP-001": ("COMPOSITION.md", "Choice routing", "CHOICE_LOOP_RUNTIME", "MECHANICAL", subsection(composition["2"][1], "2.4 Choice records") + "\n\n" + subsection(composition["4"][1], "4.1 Choice routing")),
    "COMP-002": ("COMPOSITION.md", "Bounded loops", "CHOICE_LOOP_RUNTIME", "MECHANICAL", subsection(composition["4"][1], "4.2 Cycle admission") + "\n\n" + subsection(composition["4"][1], "4.3 Choice and loop cases")),
    "DEAD-001": ("COMPOSITION.md", composition["5"][0], "DEADLINE_RUNTIME", "MECHANICAL", composition["5"][1]),
    "PAR-001": ("COMPOSITION.md", composition["6"][0], "PARALLEL_FANOUT_RUNTIME", "MECHANICAL", composition["6"][1]),
    "FAN-001": ("COMPOSITION.md", composition["7"][0], "PARALLEL_FANOUT_RUNTIME", "MECHANICAL", composition["7"][1]),
    "XPROF-001": ("COMPOSITION.md", composition["8"][0], "WORK_RUNTIME", "MECHANICAL", composition["8"][1]),
    "VALID-001": ("COMPOSITION.md", composition["9"][0], "WORK_RUNTIME", "MECHANICAL", composition["9"][1]),
    "HOST-002": ("COMPOSITION.md", composition["10"][0], "REFERENCE_SINGLE_PROCESS_CONTENTION", "MECHANICAL", composition["10"][1]),
    "CONF-001": ("COMPOSITION.md", composition["11"][0], "ADAPTER", "MIXED", composition["11"][1]),
    "RES-WIRE-001": ("RESERVATION-RECORDS.md", "Configuration and administration", "RESERVATION_TRANSITIONS", "MECHANICAL", reservation_records["Configuration and administration"]),
    "RES-001A": ("RESERVATIONS.md", "Exclusive keys in the reservation transition", "RESERVATION_TRANSITIONS", "MECHANICAL", identified["RES-001A"][2]),
    "RES-007A": ("RESERVATIONS.md", "Attributed historical exclusive-key coverage", "RESERVATION_TRANSITIONS", "MECHANICAL", identified["RES-007A"][2]),
    "RES-WIRE-002": ("RESERVATION-RECORDS.md", "Definitions and projections", "RESERVATION_TRANSITIONS", "MECHANICAL", reservation_records["Definitions and projections"]),
    "RES-WIRE-003": ("RESERVATION-RECORDS.md", "Complete history and native records", "RESERVATION_TRANSITIONS", "MECHANICAL", reservation_records["Complete history and native records"]),
    "RES-WIRE-004": ("RESERVATION-RECORDS.md", "Core transitions and state reconstruction", "RESERVATION_TRANSITIONS", "MECHANICAL", reservation_records["Core transitions and state reconstruction"]),
}

previous = {row["id"]: row for row in json.loads(OUTPUT.read_text())["requirements"]}
requirements: list[dict[str, object]] = []
all_ids = sorted(set(identified) | set(manual))
for requirement_id in all_ids:
    if requirement_id in manual:
        document, title, role, verification, behavior = manual[requirement_id]
    else:
        document, title, behavior = identified[requirement_id]
        prior = previous.get(requirement_id)
        if prior is None and requirement_id.startswith("FLOW-"):
            prior = {"role": "FLOW_TRANSITIONS" if requirement_id in {"FLOW-001", "FLOW-002", "FLOW-003"} else "AUTHORITY_EVALUATOR" if requirement_id in {"FLOW-004", "FLOW-005", "FLOW-006"} else "WORK_RUNTIME" if requirement_id == "FLOW-007" else "REFERENCE_SINGLE_PROCESS_CONTENTION", "verification": "MIXED" if requirement_id in {"FLOW-001", "FLOW-008"} else "MECHANICAL"}
        if prior is None and requirement_id.startswith("ASSESS-"):
            prior = {"role": "WORK_RUNTIME" if requirement_id == "ASSESS-006" else "AUTHORITY_EVALUATOR", "verification": "MIXED" if requirement_id == "ASSESS-006" else "MECHANICAL"}
        if prior is None and requirement_id.startswith("HOLD-"):
            prior = {"role": "AUTHORITY_EVALUATOR" if requirement_id == "HOLD-006" else "WORK_RUNTIME" if requirement_id == "HOLD-007" else "REFERENCE_SINGLE_PROCESS_CONTENTION" if requirement_id == "HOLD-008" else "HOLDINGS_TRANSITIONS", "verification": "MIXED" if requirement_id in {"HOLD-001", "HOLD-002", "HOLD-008"} else "MECHANICAL"}
        if prior is None and requirement_id.startswith("REC-"):
            prior = {"role": "WORK_RUNTIME" if requirement_id in {"REC-012", "REC-013", "REC-014", "REC-015"} else "RESERVATION_TRANSITIONS", "verification": "MIXED" if requirement_id in {"REC-003", "REC-004", "REC-005", "REC-016"} else "MECHANICAL"}
        if prior is None and requirement_id.startswith("TIME-"):
            prior = {"role": "AUTHORITY_EVALUATOR" if requirement_id == "TIME-002" else "WORK_RUNTIME",
                "verification": "MIXED" if requirement_id in {"TIME-003", "TIME-006", "TIME-008"} else "MECHANICAL"}
        if prior is None and requirement_id in {"AUTH-008", "AUTH-009", "LIFE-009B", "LIFE-006B", "LIFE-020B", "HOST-004"}:
            prior = {"role": "AUTHORITY_EVALUATOR" if requirement_id.startswith("AUTH-") else "REVIEW_EVIDENCE" if requirement_id == "LIFE-020B" else "REFERENCE_SINGLE_PROCESS_CONTENTION" if requirement_id == "HOST-004" else "WORK_RUNTIME", "verification": "MIXED" if requirement_id == "HOST-004" else "MECHANICAL"}
        if prior is None:
            raise SystemExit(f"missing role metadata for {requirement_id}")
        role = prior["role"].replace("SHARED_BUDGET_TRANSITIONS", "RESERVATION_TRANSITIONS")
        verification = prior["verification"]
    prior = previous.get(requirement_id, {})
    requirements.append(
        {
            "id": requirement_id,
            "document": document,
            "title": title,
            "role": role,
            "observable_behavior": behavior,
            "successor_disposition": "ADD" if requirement_id in {"AUTH-008", "AUTH-009", "LIFE-009B", "LIFE-006B", "LIFE-020B", "HOST-004"} or requirement_id.startswith(("REC-", "TIME-", "HOLD-", "ASSESS-", "FLOW-")) else prior.get("successor_disposition", "RESTATE"),
            "source_mapping": "conformance/work-class/1.0.0-draft.3/review/INFORMATION-FLOW-SOURCE-COVERAGE.md" if requirement_id.startswith("FLOW-") else "conformance/work-class/1.0.0-draft.3/review/ASSESSMENT-SOURCE-COVERAGE.md" if requirement_id.startswith("ASSESS-") else "conformance/work-class/1.0.0-draft.3/review/HOLDINGS-SOURCE-COVERAGE.md" if requirement_id.startswith("HOLD-") else "conformance/work-class/1.0.0-draft.3/review/CDMO-SOURCE-COVERAGE.md" if requirement_id in {"AUTH-008", "AUTH-009", "LIFE-009B", "LIFE-006B", "LIFE-020B", "HOST-004"} else "conformance/work-class/1.0.0-draft.3/review/TIMING-SOURCE-COVERAGE.md" if requirement_id.startswith("TIME-") else "conformance/work-class/1.0.0-draft.3/review/RECOVERY-SOURCE-COVERAGE.md" if requirement_id.startswith("REC-") else prior.get("source_mapping", SOURCE_MAPPING),
            "verification": verification,
            "verification_obligation": prior.get(
                "verification_obligation",
                "Complete independently derived decisive cases for every operative paragraph; host and source-truth statements require documented human assessment.",
            ),
            "evidence_status": "NEW_CANDIDATE_EVIDENCE_REQUIRED",
        }
    )

result = {
    "identity": "seampoint.work-class.requirements/1.0.0-draft.3/contract-review.3",
    "claim_ceiling": "APPARATUS_ONLY",
    "status": "DRAFT_3_CONTRACT_REVIEW",
    "requirements": requirements,
}
OUTPUT.write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps({"requirements": len(requirements), "identified": len(identified), "manual": len(manual)}))
