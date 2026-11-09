#!/usr/bin/env python3
"""Build runner-observation transport cases that produce no adapter result."""

from __future__ import annotations

import base64
import json

from corpus_common import CASES, exact_case, write_canonical_json


def main() -> None:
    malformed = (
        b'{"protocol":"seampoint.work-class.adapter/1.0.0-draft.3",'
        b'"request_id":"D2-078","operation":"step",'
        b'"input":{"kind":"PROPOSE","authority_input":{}}}'
    )
    case = exact_case(
        "D2-078",
        "transport",
        {
            "bytes_base64": base64.b64encode(malformed).decode("ascii"),
            "fault": "MISSING_TERMINATING_LF",
        },
        {
            "adapter_response": None,
            "harness_observation": "TRANSPORT_ERROR",
        },
        [],
        "The JSON text is not terminated by the required single line-feed byte. The harness records a transport failure before the incomplete authority input can be interpreted. This expected object is non-normative runner metadata; there is no adapter governance response.",
    )
    write_canonical_json(CASES / "transport-precedence" / "D2-078.json", case)
    print(json.dumps({"case_ids": ["D2-078"], "result_kind": "NON_NORMATIVE_RUNNER_OBSERVATION"}, indent=2))


if __name__ == "__main__":
    main()
