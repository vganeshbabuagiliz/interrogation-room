"""Fail if a file that would be published contains a secret (API keys, AWS keys, private keys).

    python secret_scan.py          # scans every file not excluded by .gitignore-style skips below
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PATTERNS = {
    "decider API key": re.compile(r"dcd_(live|test)_[A-Za-z0-9]{20,}"),
    "AWS access key id": re.compile(r"\b(AKIA|ASIA)[A-Z0-9]{16}\b"),
    "AWS secret key": re.compile(r"(?i)aws_secret_access_key\s*[=:]\s*['\"]?[A-Za-z0-9/+=]{40}"),
    "private key": re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    "Hugging Face token": re.compile(r"\bhf_[A-Za-z0-9]{30,}\b"),
    "bearer token": re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{24,}"),
    "key assigned in a file": re.compile(r"(?im)^\s*(DECIDER_API_KEY|LLM_API_KEY|API_KEY)\s*=\s*[\"']?[A-Za-z0-9._\-]{16,}"),
}
SKIP_DIRS = {".venv", "__pycache__", ".git", "node_modules", ".claude"}
SKIP_FILES = {".env", "files.zip", "secret_scan.py"}   # .env is gitignored; this file holds the patterns
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".mp4", ".zip", ".log", ".pyc"}


def main() -> int:
    hits = []
    for p in ROOT.rglob("*"):
        if not p.is_file() or p.name in SKIP_FILES or p.suffix in SKIP_SUFFIXES:
            continue
        if SKIP_DIRS & set(p.relative_to(ROOT).parts):
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        for name, rx in PATTERNS.items():
            for m in rx.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                hits.append(f"{p.relative_to(ROOT)}:{line}: looks like a {name}")
    if hits:
        print("SECRETS FOUND, do not publish:\n  " + "\n  ".join(hits))
        return 1
    print("secret scan: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
