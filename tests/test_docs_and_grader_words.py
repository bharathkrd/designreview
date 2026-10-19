"""
Offline tests for two word-level checkers: the ASD-STE100 docs check (scripts/ste_check.py) and the
negation handling of the geometry-claim verifier (packs/designreview/checks.py).    Markers: none

Author(s): ____________    Written by hand: [ ] yes

Background: docs/CHANGES.md entries of 2026-10-14 ("The docs in ASD-STE100", "geometry disclaimers");
tests/MANUAL_TEST_LOG.md row A-LIVE-07 (a live t10 run failed on a true disclaimer). Both exist today.

Use cases to cover:
  STE check (scripts/ste_check.py: check_file(path) -> (sentence count, [Finding]); main(argv) -> exit code):
  [ ] a sentence of 26 words -> one "sentence length" finding; 25 words -> none
  [ ] a list item that starts "Run ..." with 21 words -> a finding (instructions: 20 words or fewer)
  [ ] a paragraph of 7 short sentences -> one "paragraph" finding
  [ ] "The file is removed by the gateway." -> "passive voice"; "The gateway removes the file." -> none
  [ ] "It doesn't stop." -> "contraction"; "It does not stop." -> none
  [ ] "e.g." and "allows" -> "unapproved word" findings that name "for example" and "lets"
  [ ] the same passive or contraction inside "double quotes" -> no finding (quotations keep their wording)
  [ ] text in a ``` code fence or in `inline code` -> no finding
  [ ] "**Bold lead-in.** Then a second sentence." counts as two sentences
  [ ] main([<clean file>]) returns 0; main([<file with a finding>]) returns 1; a missing file returns 2
  [ ] the shipped docs pass: main([]) returns 0 (README.md, docs/ARCHITECTURE.md, docs/EXPLAINERS.md,
      docs/explainers/*.md)

  Geometry disclaimers (packs.designreview.checks.geometry_claims, says_ready):
  [ ] "Nothing in this answer comes from a geometry diff, 3D comparison or CAD analysis." -> no claim
  [ ] "Neither a CAD comparison nor a 3D overlay was run." and "None of this is from a geometry comparison."
      -> no claim
  [ ] "The geometry comparison shows the wall is 2.5 mm thicker." -> a claim
  [ ] "The geometry comparison shows nonetheless a thicker wall." -> a claim ("nonetheless" denies nothing)
  [ ] says_ready("Nothing blocks it; it is ready for release.") is still True (the new words apply only to
      the geometry check)

More use cases (added 2026-10-16, to write by hand):
  [ ] a Markdown table cell is checked on its own: a 26-word cell -> one "sentence length" finding,
      and a list item that starts "Run" inside a table cell keeps the 25-word limit
  [ ] "is open", "is given", "is broken" are not passive voice (NOT_PARTICIPLE); "is removed" is
  [ ] a link "[the guide](docs/a_very_long_path.md)" counts the link text only, not the target
Hint: scripts/ is not a package. Load the script with
importlib.util.spec_from_file_location("ste_check", <repo>/scripts/ste_check.py), then module_from_spec and
spec.loader.exec_module. Put the module in sys.modules["ste_check"] BEFORE exec_module: the script has
a @dataclass, which looks its module up there. Write sample Markdown files to tmp_path.
"""

import importlib.util
from pathlib import Path

import pytest

from packs.designreview.checks import geometry_claims, says_ready

# Write your tests below.
