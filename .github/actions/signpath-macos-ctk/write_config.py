#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import pathlib
import sys


def main() -> None:
    pathlib.Path(sys.argv[1]).write_text(
        json.dumps(
            {
                "ApiUrl": "https://app.signpath.io/Api",
                "OrganizationId": os.environ["SIGNPATH_ORGANIZATION_ID"],
                "ApiToken": os.environ["SIGNPATH_API_TOKEN"],
                "ProjectSlug": os.environ["SIGNPATH_PROJECT_SLUG"],
                "SigningPolicySlug": os.environ["SIGNPATH_SIGNING_POLICY_SLUG"],
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
