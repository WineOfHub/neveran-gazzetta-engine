"""Scansione locale conservativa per segreti commessi accidentalmente."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IGNORED_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".wrangler",
    "__pycache__",
    "artifacts",
    "build",
    "dist",
    "runtime",
    "node_modules",
}
PATTERNS = {
    "private-key": re.compile("-----BEGIN " + r"(?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "github-token": re.compile(r"gh[pousr]" + r"_[A-Za-z0-9]{30,}"),
    "groq-key": re.compile(r"gsk" + r"_[A-Za-z0-9]{20,}"),
    "jwt": re.compile(r"eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{10,}"),
}


def candidate_files() -> list[Path]:
    try:
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return sorted(
            path
            for path in ROOT.rglob("*")
            if path.is_file()
            and path.name != ".env"
            and not path.name.startswith(".env.")
            and not any(part in IGNORED_PARTS for part in path.parts)
        )
    return sorted(
        ROOT / item.decode("utf-8")
        for item in result.stdout.split(b"\0")
        if item and (ROOT / item.decode("utf-8")).is_file()
    )


def main() -> int:
    findings: list[str] = []
    for path in candidate_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for name, pattern in PATTERNS.items():
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                findings.append(f"{path.relative_to(ROOT)}:{line}: possibile {name}")
    if findings:
        print("\n".join(findings), file=sys.stderr)
        return 1
    print("Nessun segreto riconoscibile trovato.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
