#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import subprocess
import sys

IDENTITY_RE = re.compile(r'^\s*\d+\)\s+([A-F0-9]{40})\s+"(.*)"\s*$')


def normalize(value: str) -> str:
    return value.replace("'", "").replace('"', "").replace("[", "").replace("]", "")


def identities(*, policy: str | None, valid_only: bool) -> list[tuple[str, str]]:
    cmd = ["security", "find-identity"]
    if valid_only:
        cmd.append("-v")
    if policy:
        cmd.extend(["-p", policy])
    out = subprocess.check_output(cmd, text=True)
    found: list[tuple[str, str]] = []
    for line in out.splitlines():
        match = IDENTITY_RE.match(line)
        if match:
            found.append((match.group(1), match.group(2)))
    return found


def matches(name: str, needle: str) -> bool:
    return needle in name or normalize(needle) in normalize(name)


def main() -> None:
    needle = os.environ["SIGNPATH_CERTIFICATE_SUBJECT_NAME"]
    searches = (
        {"policy": "codesigning", "valid_only": True},
        {"policy": "codesigning", "valid_only": False},
        # A SignPath test cert is not an Apple Developer ID, so Apple's
        # codesigning policy often hides it. codesign can still use the hash.
        {"policy": None, "valid_only": False},
    )
    for search in searches:
        for fingerprint, name in identities(**search):
            if matches(name, needle):
                print(fingerprint, end="")
                return
    raise SystemExit(1)


if __name__ == "__main__":
    main()
