#!/usr/bin/env python3
from __future__ import annotations

import base64
import json
import pathlib
import sys


def main() -> None:
    policies_path = pathlib.Path(sys.argv[1])
    cert_path = pathlib.Path(sys.argv[2])
    data = json.loads(policies_path.read_text())
    policies = data.get("signingPolicies") or data
    if isinstance(policies, dict):
        policies = policies.get("signingPolicies") or [policies]
    if not policies:
        raise SystemExit(f"SignPath returned no signing policies: {data!r}")
    cert_b64 = policies[0].get("certificateBytes")
    if not cert_b64:
        raise SystemExit(f"Signing policy is missing certificateBytes: {list(policies[0])}")
    cert_path.write_bytes(base64.b64decode(cert_b64))
    print(f"Wrote {cert_path} ({cert_path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
