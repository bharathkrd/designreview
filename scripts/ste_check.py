"""
Check Markdown docs against the measurable writing rules of ASD-STE100 (Simplified Technical English).

    python scripts/ste_check.py                   # docs/ARCHITECTURE.md, docs/EXPLAINERS.md, docs/explainers/*.md
    python scripts/ste_check.py docs/x.md ...     # the given files
    python scripts/ste_check.py --detail          # also each finding (CI always prints them)

Exit 1 when a file has a finding. Standard library only.

Measured (approximations of the STE writing rules):
  sentence length   a descriptive sentence has 25 words or fewer; the first sentence of a list item
                    that starts with an instruction verb ("Run ...", "Set ...") has 20 or fewer
  paragraph length  6 sentences or fewer (a list item and a table cell count as paragraphs)
  passive voice     a be-verb + past participle ("is removed"): write the agent of the action
  contractions      "can't", "doesn't", "it's" ...: write the full words
  unapproved words  a short list of common words that STE replaces ("allows" -> "lets",
                    "provides" -> "gives", "e.g." -> "for example" ...)
Not measured: the full STE dictionary, the technical-name and technical-verb categories, one meaning
for each word. A clean result is necessary for STE, but it is not proof of STE.

What the check ignores:
  - fenced code blocks, and `inline code` (it counts as one word);
  - link targets;
  - text in quotation marks for passive voice, contractions and unapproved words: a quotation
    gives original text exactly (it still counts for sentence length).
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FILES = [ROOT / "docs" / "ARCHITECTURE.md", ROOT / "docs" / "EXPLAINERS.md",
                 *sorted((ROOT / "docs" / "explainers").glob("*.md"))]

MAX_DESCRIPTIVE = 25
MAX_PROCEDURAL = 20
MAX_PARAGRAPH = 6

UNAPPROVED = {
    "ensure": "make sure", "ensures": "makes sure", "utilize": "use", "utilise": "use", "via": "through",
    "prior": "before", "approximately": "about", "whilst": "while", "therefore": "thus",
    "e.g.": "for example", "i.e.": "that is", "etc.": "(list all items)", "obtain": "get",
    "require": "need", "requires": "needs", "required": "necessary", "allow": "let", "allows": "lets",
    "provide": "give", "provides": "gives", "contain": "have", "contains": "has", "perform": "do",
    "performs": "does",
}
PASSIVE = re.compile(r"\b(?:is|are|was|were|be|been|being)\s+(?:\w+ly\s+)?(\w+(?:ed|en))\b", re.I)
NOT_PARTICIPLE = {"open", "often", "token", "tokens", "hidden", "even", "seven", "between", "given", "broken",
                  "golden", "listen", "kitchen", "garden"}
CONTRACTION = re.compile(r"\b\w+(?:n't|'re|'ll|'ve|'d)\b|\b(?:it|that|what|there|here|who|let)'s\b", re.I)
PROCEDURAL = re.compile(r"^\s*(?:[-*]|\d+\.)\s+(?:\*\*)?(?:run|set|add|use|remove|delete|start|stop|read|write|"
                        r"make|do|check|open|install|copy|type|call|put|give|send|change|keep)\b", re.I)
QUOTED = re.compile(r"\"[^\"]*\"|“[^”]*”")
CODE = re.compile(r"`[^`]*`")


@dataclass
class Finding:
    path: Path
    line: int
    rule: str
    text: str


def blocks(text: str) -> Iterator[Tuple[int, str, bool]]:
    """(first line number, text, is_table_cell): paragraphs, list items and table cells; no code."""
    text = re.sub(r"```.*?```", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    cur: List[str] = []
    start = 0
    for n, line in enumerate(text.split("\n"), 1):
        s = line.strip()
        boundary = not s or s.startswith("#") or re.match(r"^\|?[-:| ]+\|?$", s)
        new_item = bool(re.match(r"^([-*]|\d+\.)\s", s)) or s.startswith("|")
        if (boundary or new_item) and cur:
            yield start, " ".join(cur), False
            cur = []
        if boundary:
            continue
        if s.startswith("|"):
            for cell in s.strip("|").split("|"):
                if cell.strip():
                    yield n, cell.strip(), True
            continue
        if not cur:
            start = n
        cur.append(s)
    if cur:
        yield start, " ".join(cur), False


def sentences(block: str) -> List[str]:
    b = CODE.sub("CODE", block)
    b = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", b)
    b = re.sub(r"\b(e\.g|i\.e|etc|vs)\.", r"\1", b)
    b = re.sub(r"([.!?:])\*\*\s+", r"\1 ", b)  # a bold lead-in ("**Do X.** Then ...") is its own sentence
    return [s for s in re.split(r"(?<=[.!?])\s+(?=[A-Z*`(\"])", b) if re.search(r"[A-Za-z]", s)]


def words(sentence: str) -> List[str]:
    return re.findall(r"[A-Za-z0-9][\w'./-]*", sentence)


def check_file(path: Path) -> Tuple[int, List[Finding]]:
    out: List[Finding] = []
    count = 0
    for line, block, cell in blocks(path.read_text(encoding="utf-8")):
        ss = sentences(block)
        count += len(ss)
        if len(ss) > MAX_PARAGRAPH:
            out.append(Finding(path, line, "paragraph", f"{len(ss)} sentences (max {MAX_PARAGRAPH}): {block[:70]}"))
        for i, s in enumerate(ss):
            limit = MAX_PROCEDURAL if (i == 0 and not cell and PROCEDURAL.match(block)) else MAX_DESCRIPTIVE
            n = len(words(s))
            if n > limit:
                out.append(Finding(path, line, "sentence length", f"{n} words (max {limit}): {s[:90]}"))
            own = QUOTED.sub("", s)  # a quotation keeps its original wording
            for m in PASSIVE.finditer(own):
                if m.group(1).lower() not in NOT_PARTICIPLE:
                    out.append(Finding(path, line, "passive voice", f"'{m.group(0)}': name who does the action"))
            for c in CONTRACTION.findall(own):
                out.append(Finding(path, line, "contraction", f"'{c}': write the full words"))
            for w in re.findall(r"\b[a-z][a-z.]*\b", own.lower()):
                key = w if w in UNAPPROVED else w.rstrip(".")
                if key in ("e.g", "i.e", "etc"):  # sentences() took the last dot off these
                    key += "."
                if key in UNAPPROVED:
                    out.append(Finding(path, line, "unapproved word", f"'{key}' -> '{UNAPPROVED[key]}'"))
    return count, out


def main(argv: List[str] = None) -> int:
    ap = argparse.ArgumentParser(description="Check Markdown docs against the measurable ASD-STE100 rules.")
    ap.add_argument("files", nargs="*", type=Path, help="default: docs/ARCHITECTURE.md, docs/EXPLAINERS.md and docs/explainers/*.md")
    ap.add_argument("--detail", action="store_true", help="print each finding (on in GitHub Actions)")
    args = ap.parse_args(argv)
    files = args.files or DEFAULT_FILES
    ci = os.environ.get("GITHUB_ACTIONS") == "true"
    rows, total = [], 0
    for path in files:
        path = path.resolve()
        if not path.exists():
            print(f"{path}: not found", file=sys.stderr)
            return 2
        count, found = check_file(path)
        total += len(found)
        name = path.relative_to(ROOT).as_posix() if path.resolve().is_relative_to(ROOT) else str(path)
        rows.append((name, count, len(found)))
        print(f"{name:45} {count:4} sentences  {len(found):3} findings")
        for f in found if (args.detail or ci) else []:
            print(f"    line {f.line}: {f.rule}: {f.text}")
            if ci:
                print(f"::error file={name},line={f.line},title=ASD-STE100 {f.rule}::{f.text}")
    print(f"\n{total} finding(s) in {len(files)} file(s).")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("### ASD-STE100 check\n\n| File | Sentences | Findings |\n|---|---|---|\n")
            fh.writelines(f"| `{n}` | {c} | {k} |\n" for n, c, k in rows)
            fh.write(f"\n**{total} finding(s) in {len(files)} file(s).**\n")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
