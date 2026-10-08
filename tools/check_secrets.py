"""Scan staged files and optional Git history without printing credentials."""
from pathlib import Path
import argparse
import json
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = [re.compile(r"sk-[A-Za-z0-9_-]{20,}"), re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"), re.compile(r"github_pat_[A-Za-z0-9_]{20,}")]


def git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, check=True).stdout


def local_values():
    path = Path.home() / ".config/PDFMathTranslate/config.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [value.encode() for item in data.get("translators", []) for key, value in item.get("envs", {}).items()
            if isinstance(value, str) and len(value) > 12 and (key.endswith("_API_KEY") or key.endswith("_BASE_URL"))]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--history", action="store_true")
    args = parser.parse_args()
    known = local_values()
    files = {}
    for path in git("diff", "--cached", "--name-only", "--diff-filter=ACMR").decode().splitlines():
        files[("staged", path)] = git("show", ":" + path)
    if args.history:
        for commit in git("rev-list", "--all").decode().splitlines():
            for path in git("ls-tree", "-r", "--name-only", commit).decode().splitlines():
                files[(commit[:8], path)] = git("show", commit + ":" + path)
    found = []
    for (revision, path), content in files.items():
        text = content.decode("utf-8", errors="replace")
        if any(p.search(text) for p in PATTERNS) or any(value in content for value in known):
            found.append(f"{revision}: {path}: credential or local API address detected")
    if found:
        print("\n".join(found))
        return 1
    print(f"Secret check passed ({len(files)} file revisions). No credential values displayed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
