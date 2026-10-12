"""
Look for credentials in the repository -- standard library only, so it runs
anywhere CI runs (and before anything is installed).

    python scripts/secret_scan.py                 # every tracked file (git ls-files)
    python scripts/secret_scan.py PATH [PATH...]  # these files / folders (e.g. runs/ before an upload)
    python scripts/secret_scan.py --history       # every line ever added, on every branch

Exit 1 if anything is found, 0 otherwise. Findings name the rule, the file
(and commit, in --history) and the line -- never the secret itself: only its
first four characters and its length are printed.

Rules cover the credentials this project actually handles: AgentSwitch bearer
tokens (JWTs), the LLM providers' API keys (Anthropic, OpenAI, OpenRouter,
Gemini, Groq, NVIDIA, Cerebras), an UPPER_CASE secret-looking variable or a
quoted password/secret/token/api_key given a literal value, and any committed
.env file. Placeholders (`<your-password>`, `os.getenv(...)`, `${VAR}`) pass.

Runs alongside gitleaks (.gitleaks.toml) in CI: two independent scanners, so
one tool's blind spot is not the project's.

Provenance: written for this project; the idea of a dependency-free history
scanner next to gitleaks is referred from an outside source.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, List, Optional, Tuple

RULES: List[Tuple[str, re.Pattern]] = [
    ("jwt-bearer-token", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{20,}")),
    ("anthropic-api-key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}")),
    ("openrouter-api-key", re.compile(r"\bsk-or-[A-Za-z0-9_-]{20,}")),
    ("openai-api-key", re.compile(r"\bsk-(?!ant-|or-)(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}")),
    ("gemini-api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{30,}")),
    ("groq-api-key", re.compile(r"\bgsk_[A-Za-z0-9]{20,}")),
    ("nvidia-api-key", re.compile(r"\bnvapi-[A-Za-z0-9_-]{20,}")),
    ("cerebras-api-key", re.compile(r"\bcsk-[A-Za-z0-9]{20,}")),
    # ENV-style assignment of a literal: AS_SURYODAYA_PASSWORD=..., GROQ_API_KEY: "..."
    ("secret-assignment", re.compile(
        r"\b[A-Z0-9_]*(?:PASSWORD|PASSWD|SECRET|TOKEN|API_KEY)[A-Z0-9_]*\s*[:=]\s*[\"']?"
        r"(?P<value>[^\s\"'<>(){}\[\]$,;]{8,})(?=[\"'\s,;]|$)")),
    # a quoted literal in code: password="...", "api_key": "..."
    ("secret-literal", re.compile(
        r"(?i)[\"']?\b(?:password|passwd|secret|api_key|apikey|token)[\"']?\s*[:=]\s*[\"']"
        r"(?P<value>[^\"'\s<>{}$]{8,})[\"']")),
]

# Values that look like secrets but are not: test fakes and documentation placeholders.
PLACEHOLDER = re.compile(r"(?i)^(?:x+|\*+|changeme|change_me|password|secret|example\w*|your\w*|dummy\w*|"
                         r"fake\w*|test\w*|placeholder\w*|redacted|none|null|true|false)$")
ASSIGNMENT_RULES = {"secret-assignment", "secret-literal"}


def looks_like_a_credential(value: str) -> bool:
    """An assignment's value is reported only if it mixes letters and digits
    (identifiers such as "token_expired" or type names are not credentials).
    Provider-key rules above are matched by shape and need no such test."""
    return any(c.isdigit() for c in value) and any(c.isalpha() for c in value)


ENV_FILE = re.compile(r"(^|/)\.env(\.[^/]*)?$")
ENV_FILE_OK = re.compile(r"(^|/)\.env\.(example|sample|template)$")
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".gz", ".whl", ".pyc"}
MAX_BYTES = 5_000_000


@dataclass(frozen=True)
class Finding:
    rule: str
    origin: str  # path, or commit:path in --history
    line: int
    value: str

    def render(self) -> str:
        return f"  {self.rule:20} {self.origin}:{self.line}  {self.value[:4]}... ({len(self.value)} chars)"


def scan_text(text: str, origin: str) -> List[Finding]:
    found: List[Finding] = []
    for n, line in enumerate(text.splitlines(), 1):
        taken: List[Tuple[int, int]] = []  # spans already reported by an earlier, more specific rule
        for rule, pattern in RULES:
            for m in pattern.finditer(line):
                value = m.group("value") if "value" in pattern.groupindex else m.group(0)
                start, end = (m.start("value"), m.end("value")) if "value" in pattern.groupindex else m.span()
                if any(s < end and start < e for s, e in taken) or PLACEHOLDER.match(value):
                    continue
                if rule in ASSIGNMENT_RULES and not looks_like_a_credential(value):
                    continue
                taken.append((start, end))
                found.append(Finding(rule, origin, n, value))
    return found


def scan_file(path: Path, display: Optional[str] = None) -> List[Finding]:
    name = display or path.as_posix()
    if ENV_FILE.search(name) and not ENV_FILE_OK.search(name):
        return [Finding("committed-env-file", name, 0, path.name)]
    if path.suffix.lower() in SKIP_SUFFIXES or not path.is_file() or path.stat().st_size > MAX_BYTES:
        return []
    raw = path.read_bytes()
    if b"\x00" in raw[:8192]:
        return []  # binary
    return scan_text(raw.decode("utf-8", errors="replace"), name)


def _git(args: List[str], cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=True).stdout


def tracked_files(root: Path) -> List[Path]:
    return [root / p for p in _git(["ls-files", "-z"], root).split("\0") if p]


def walk(paths: Iterable[Path]) -> Iterator[Path]:
    for p in paths:
        if p.is_dir():
            yield from sorted(x for x in p.rglob("*") if x.is_file() and "__pycache__" not in x.parts)
        else:
            yield p


def scan_history(root: Path) -> List[Finding]:
    """Every added line of every commit on every ref (`git log -p --all`)."""
    out = _git(["log", "-p", "--all", "--no-color", "--unified=0", "--format=commit %H"], root)
    found: List[Finding] = []
    commit, path, line_no = "", "", 0
    for raw in out.splitlines():
        if raw.startswith("commit ") and len(raw) == 47:
            commit = raw[7:19]
        elif raw.startswith("+++ "):
            path = raw[6:] if raw.startswith("+++ b/") else ""
            if path and ENV_FILE.search(path) and not ENV_FILE_OK.search(path):
                found.append(Finding("committed-env-file", f"{commit}:{path}", 0, Path(path).name))
        elif raw.startswith("@@"):
            m = re.search(r"\+(\d+)", raw)
            line_no = int(m.group(1)) if m else 0
        elif raw.startswith("+") and path:
            found += [Finding(f.rule, f"{commit}:{path}", line_no, f.value) for f in scan_text(raw[1:], path)]
            line_no += 1
    return found


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Scan for committed credentials (stdlib only).")
    ap.add_argument("paths", nargs="*", type=Path, help="files or folders (default: every tracked file)")
    ap.add_argument("--history", action="store_true", help="scan every line ever added, on every branch")
    args = ap.parse_args(argv)
    root = Path.cwd()
    if args.history:
        if args.paths:
            ap.error("--history scans the whole repository; give no paths")
        findings = scan_history(root)
        what = "git history (all refs)"
    elif args.paths:
        findings = [f for p in walk(args.paths) for f in scan_file(p)]
        what = ", ".join(str(p) for p in args.paths)
    else:
        top = Path(_git(["rev-parse", "--show-toplevel"], root).strip())
        findings = [f for p in tracked_files(top) for f in scan_file(p, p.relative_to(top).as_posix())]
        what = "tracked files"
    if findings:
        print(f"secret scan: {len(findings)} possible credential(s) in {what}:")
        for f in findings:
            print(f.render())
        print("Rotate any real credential, then remove it (from history too). Values are not printed.")
        return 1
    print(f"secret scan: clean ({what})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
