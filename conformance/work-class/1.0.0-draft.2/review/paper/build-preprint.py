#!/usr/bin/env python3
"""Build the arXiv-style preprint from the current review paper."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "WHITE-PAPER-1.0-r3b.md"
MARKDOWN = ROOT / "preprint.md"
TEX = ROOT / "preprint.tex"
PDF = ROOT / "preprint.pdf"

ABSTRACT = """Agentic systems can authenticate, call approved tools and follow their instructions while still performing unauthorized business acts. Conventional controls often bind identity and tool access without preserving the authority, cumulative exposure, legal state and effect evidence of one specific work instance. This paper presents the Work-Class Governance Specification, a portable deterministic contract for bounded consequential work. A work class names the operations and objects in scope, required authority, typed constraints, shared limits, valid transitions and evidence of completion. A conforming consumer evaluates explicit artifacts, observations, events and state; the host commits the returned transition, enforces it at native dispatch and reports effect evidence through the same work identity. Candidate `seampoint.work-class/1.0.0-draft.2` contains 80 requirements and 425 frozen cases. TypeScript and Python reference consumers reproduce every case byte for byte, and four synthetic specimens apply the same contract in access, money, care and force. The evidence establishes a reviewable specification and conformance apparatus for the declared profiles. It does not qualify a production host, establish source-policy fidelity, prove operational benefit or supply facts that remain the host's responsibility."""

FRONT_MATTER = f"""---
title: "Governance Belongs to the Work"
subtitle: "The Work-Class Governance Specification for Consequential Agentic Systems"
author: "Jeff Whatcott (Seampoint)"
date: "September 14, 2026"
lang: en-US
abstract: |
  {ABSTRACT}
keywords:
  - agentic AI governance
  - deterministic governance
  - work-class specification
  - business authority
  - conformance testing
  - shared reservations
papersize: letter
fontsize: 11pt
geometry: margin=1in
colorlinks: true
linkcolor: blue
citecolor: black
urlcolor: blue
---

**Keywords:** agentic AI governance; deterministic governance; work-class specification; business authority; conformance testing; shared reservations

*Open review preprint. Candidate `seampoint.work-class/1.0.0-draft.2`, pin `sha256:5442ee3b55675d849e388981487b806c0be29f686df6df8520b488508f86ceec`. Not posted to arXiv.*

"""


def paper_body() -> str:
    source = SOURCE.read_text()
    start = source.index("## 1. ")
    body = source[start:]
    body = body.replace(
        "Every figure in this section comes from the draft 2 freeze record at pin "
        "`sha256:5442ee3b55675d849e388981487b806c0be29f686df6df8520b488508f86ceec`. "
        "Draft 1’s results stay attached to draft 1.",
        "Every figure in this section comes from the draft 2 freeze record at the following candidate pin. "
        "Draft 1’s results stay attached to draft 1.\n\n"
        "```text\nsha256:5442ee3b55675d849e388981487b806c0be29f686df6df8520b488508f86ceec\n```",
    )
    body = re.sub(r"^## ([0-9]+)\. ", "# ", body, flags=re.MULTILINE)
    body = re.sub(r"^### ([0-9]+\.[0-9]+)\.?\s+", "## ", body, flags=re.MULTILINE)
    body = re.sub(r"^#### ([0-9]+(?:\.[0-9]+)+)\.?\s+", "### ", body, flags=re.MULTILINE)
    return body


def build() -> None:
    pandoc = shutil.which("pandoc")
    xelatex = shutil.which("xelatex")
    if not pandoc or not xelatex:
        raise SystemExit("pandoc and xelatex must be available on PATH")

    MARKDOWN.write_text(FRONT_MATTER + paper_body())
    common = [
        pandoc,
        MARKDOWN.name,
        "--standalone",
        "--number-sections",
        "--listings",
        "--resource-path=.",
        "-H",
        "arxiv-header.tex",
        "-V",
        "documentclass=article",
        "-V",
        "fontsize=11pt",
        "-V",
        "papersize=letter",
        "-V",
        "geometry:margin=1in",
        "-V",
        "linestretch=1.0",
        "-V",
        "colorlinks=true",
        "-V",
        "linkcolor=blue",
        "-V",
        "urlcolor=blue",
    ]
    subprocess.run(common + ["--pdf-engine=xelatex", f"--output={PDF.name}"], cwd=ROOT, check=True)
    subprocess.run(common + ["--to=latex", f"--output={TEX.name}"], cwd=ROOT, check=True)


if __name__ == "__main__":
    build()
    print(f"wrote {MARKDOWN.name}, {TEX.name}, and {PDF.name}")
