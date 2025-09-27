#!/usr/bin/env python3
"""Utility to export pinned dependencies from pyproject.toml to a requirements file."""
from __future__ import annotations

import argparse
import pathlib
import sys
from typing import Iterable, List

try:  # Python 3.11+
    import tomllib  # type: ignore[attr-defined]
except ModuleNotFoundError:  # pragma: no cover - fallback for <3.11
    import tomli as tomllib  # type: ignore


def load_pyproject(pyproject_path: pathlib.Path) -> dict:
    if not pyproject_path.exists():
        raise FileNotFoundError(f"pyproject.toml not found at {pyproject_path}")
    return tomllib.loads(pyproject_path.read_text(encoding="utf-8"))


def merge_dependencies(primary: Iterable[str], extras: Iterable[str]) -> List[str]:
    seen = set()
    ordered: List[str] = []
    for source in (primary, extras):
        for item in source:
            normalized = item.strip()
            if not normalized or normalized.startswith("#"):
                continue
            if normalized not in seen:
                seen.add(normalized)
                ordered.append(normalized)
    return ordered


def write_requirements(dependencies: Iterable[str], output: pathlib.Path) -> None:
    header = "# This file is auto-generated from pyproject.toml. Do not edit manually.\n"
    output.write_text(header + "\n".join(dependencies) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pyproject",
        type=pathlib.Path,
        default=pathlib.Path("pyproject.toml"),
        help="Path to pyproject.toml (default: ./pyproject.toml)",
    )
    parser.add_argument(
        "--output",
        type=pathlib.Path,
        default=pathlib.Path("requirements.txt"),
        help="Target requirements.txt path",
    )
    parser.add_argument(
        "--include-extra",
        action="append",
        default=[],
        dest="extras",
        help="Optional dependency groups from pyproject to include (can be repeated)",
    )
    parser.add_argument(
        "--include-dev",
        action="store_true",
        help="Shortcut for --include-extra dev",
    )
    args = parser.parse_args(argv)

    data = load_pyproject(args.pyproject)
    project = data.get("project")
    if not project:
        raise SystemExit("[pyproject.toml] missing [project] table")

    dependencies = project.get("dependencies", [])
    optional = project.get("optional-dependencies", {})

    extras_to_include = list(args.extras)
    if args.include_dev and "dev" not in extras_to_include:
        extras_to_include.append("dev")

    extras_list: list[str] = []
    for extra_name in extras_to_include:
        extra_deps = optional.get(extra_name)
        if not extra_deps:
            raise SystemExit(f"Optional dependency group '{extra_name}' not found in pyproject.toml")
        extras_list.extend(extra_deps)

    merged = merge_dependencies(dependencies, extras_list)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_requirements(merged, args.output)

    print(f"Generated {args.output} with {len(merged)} dependencies")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
