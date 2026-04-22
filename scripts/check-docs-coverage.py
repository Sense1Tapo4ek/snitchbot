#!/usr/bin/env python3
"""Fail if snitchbot.__all__ disagrees with site/src/content/docs/api/*.mdx."""

import importlib
import pathlib
import re
import sys


def main() -> int:
    api_dir = pathlib.Path(__file__).resolve().parents[1] / "site" / "src" / "content" / "docs" / "api"
    if not api_dir.is_dir():
        print(f"error: docs dir not found: {api_dir}", file=sys.stderr)
        return 2

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
    mod = importlib.import_module("snitchbot")

    deprecated = {"RssSpikeConfig", "CpuSustainedConfig", "FdLeakConfig", "ThreadGrowthConfig"}
    ignored = deprecated | {"__version__"}
    exported = set(mod.__all__) - ignored

    documented: set[str] = set()
    errors: list[str] = []
    for mdx in sorted(api_dir.glob("*.mdx")):
        text = mdx.read_text(encoding="utf-8")
        m = re.search(r"^symbol:\s*(\w+)\s*$", text, re.M)
        if not m:
            errors.append(f"{mdx.name}: missing `symbol:` in frontmatter")
            continue
        documented.add(m.group(1))

    missing = exported - documented
    extra = documented - exported
    deprecated_docs = documented & deprecated

    if missing:
        errors.append(f"missing docs for: {sorted(missing)}")
    if extra:
        errors.append(f"docs without __all__ entry: {sorted(extra)}")
    if deprecated_docs:
        errors.append(f"deprecated symbols must not be documented: {sorted(deprecated_docs)}")

    if errors:
        for e in errors:
            print(e, file=sys.stderr)
        return 1

    print(f"docs coverage OK: {len(documented)} symbols documented")
    return 0


if __name__ == "__main__":
    sys.exit(main())
