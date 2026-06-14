#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT_PATH = Path(__file__).resolve().parents[1]
DEFAULT_C1_JSON = ROOT_PATH / "carveracontroller" / "config_c1.json"
DEFAULT_CA1_JSON = ROOT_PATH / "carveracontroller" / "config_ca1.json"
SKIPPED_SETTING_TYPES = {"button", "title"}
SKIPPED_SETTING_KEYS = {"restore", "default", "backup"}


@dataclass(frozen=True)
class UpdateResult:
    path: Path
    changed: int
    unchanged: int
    missing: tuple[str, ...]
    written: bool


def parse_config_defaults(config_path: Path) -> dict[str, str]:
    defaults: dict[str, str] = {}

    for raw_line in config_path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue

        parts = line.split(None, 1)
        if len(parts) != 2:
            continue

        key, value = parts
        defaults[key] = value.strip()

    return defaults


def iter_setting_items(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from iter_setting_items(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_setting_items(child)


def update_json_defaults(
    json_path: Path,
    defaults: dict[str, str],
    *,
    check: bool = False,
) -> UpdateResult:
    data = json.loads(json_path.read_text(encoding="utf-8"))
    changed = 0
    unchanged = 0
    missing: list[str] = []

    for setting in iter_setting_items(data):
        key = setting.get("key")
        if not isinstance(key, str):
            continue
        if key in SKIPPED_SETTING_KEYS:
            continue
        if setting.get("type") in SKIPPED_SETTING_TYPES:
            continue

        if key not in defaults:
            missing.append(key)
            continue

        default = defaults[key]
        if setting.get("default") == default:
            unchanged += 1
            continue

        setting["default"] = default
        changed += 1

    written = False
    if changed and not check:
        json_path.write_text(json.dumps(data, indent=4) + "\n", encoding="utf-8")
        written = True

    return UpdateResult(
        path=json_path,
        changed=changed,
        unchanged=unchanged,
        missing=tuple(sorted(missing)),
        written=written,
    )


def update_default_files(
    config_default_path: Path,
    config2_default_path: Path,
    *,
    c1_json_path: Path = DEFAULT_C1_JSON,
    ca1_json_path: Path = DEFAULT_CA1_JSON,
    check: bool = False,
) -> dict[str, UpdateResult]:
    c1_defaults = parse_config_defaults(config_default_path)
    ca1_defaults = parse_config_defaults(config2_default_path)

    return {
        "C1": update_json_defaults(c1_json_path, c1_defaults, check=check),
        "CA1": update_json_defaults(ca1_json_path, ca1_defaults, check=check),
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Set controller JSON default values from firmware config files. "
            "C1 uses config.default; CA1 uses config2.default."
        )
    )
    parser.add_argument("config_default", type=Path, help="Firmware src/config.default path")
    parser.add_argument("config2_default", type=Path, help="Firmware src/config2.default path")
    parser.add_argument(
        "--c1-json",
        type=Path,
        default=DEFAULT_C1_JSON,
        help=f"Controller C1 settings JSON path, default: {DEFAULT_C1_JSON}",
    )
    parser.add_argument(
        "--ca1-json",
        type=Path,
        default=DEFAULT_CA1_JSON,
        help=f"Controller CA1 settings JSON path, default: {DEFAULT_CA1_JSON}",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Report pending changes without writing JSON files; exits 1 if changes are needed.",
    )
    parser.add_argument(
        "--strict-missing",
        action="store_true",
        help="Exit 1 if any controller setting key has no active firmware config assignment.",
    )
    return parser


def print_results(results: dict[str, UpdateResult]) -> None:
    for model, result in results.items():
        action = "would update" if not result.written and result.changed else "updated"
        if not result.changed:
            action = "up to date"
        print(f"{model}: {action} {result.changed} defaults in {result.path} ({result.unchanged} already matched)")
        if result.missing:
            print(f"{model}: no active firmware default for: {', '.join(result.missing)}")


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    results = update_default_files(
        args.config_default,
        args.config2_default,
        c1_json_path=args.c1_json,
        ca1_json_path=args.ca1_json,
        check=args.check,
    )
    print_results(results)

    has_changes = any(result.changed for result in results.values())
    has_missing = any(result.missing for result in results.values())
    if (args.check and has_changes) or (args.strict_missing and has_missing):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
