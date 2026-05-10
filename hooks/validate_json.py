#!/usr/bin/env python3
"""Validate knowledge entry JSON files against the canonical schema.

Checks:
  - JSON parseability
  - Required fields: id, title, source_url, summary, tags, status
  - id format: {source}-{YYYYMMDD}-{NNN}
  - status in {draft, review, published, archived}
  - source_url format (http/https)
  - summary >= 20 chars, tags >= 1 item
  - Optional: score 1-10, audience in {beginner, intermediate, advanced}

Usage:
  python hooks/validate_json.py <json_file|pattern> [json_file2 ...]
  python hooks/validate_json.py knowledge/analyzed/*.json
  python hooks/validate_json.py knowledge/raw/*.json knowledge/analyzed/*.json
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

# ── schema constants ────────────────────────────────────────────────

REQUIRED_FIELDS: dict[str, type] = {
    "id": str,
    "title": str,
    "source_url": str,
    "summary": str,
    "tags": list,
    "status": str,
}

VALID_STATUSES: frozenset[str] = frozenset({"draft", "review", "published", "archived"})
VALID_AUDIENCES: frozenset[str] = frozenset({"beginner", "intermediate", "advanced"})

_ID_PATTERN = re.compile(r"^[a-z][a-z0-9]*-\d{8}-\d{3}$")
_URL_PATTERN = re.compile(r"^https?://\S+$")

MIN_SUMMARY_LEN: int = 20
SCORE_MIN: int = 1
SCORE_MAX: int = 10


# ── file discovery ──────────────────────────────────────────────────


def expand_files(paths: list[str]) -> list[Path]:
    """Resolve file paths and glob patterns to a sorted list of unique Paths."""
    combined: dict[str, Path] = {}
    for arg in paths:
        has_glob = "*" in arg or "?" in arg or "[" in arg
        if has_glob:
            for matched in sorted(Path().glob(arg)):
                combined[str(matched)] = matched
        else:
            p = Path(arg)
            if p.is_file():
                combined[str(p)] = p
            else:
                print(f"Warning: skipping non-existent file: {arg}", file=sys.stderr)
    return list(combined.values())


# ── JSON parsing ────────────────────────────────────────────────────


def parse_json(filepath: Path) -> Any | None:
    """Load and parse a JSON file.  Returns ``None`` on any failure."""
    try:
        with filepath.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None


def extract_entries(data: Any) -> list[dict[str, Any]]:
    """Extract a flat list of entry dicts from parsed JSON.

    Handles three top-level shapes:
      - ``[{...}, ...]``  (array of entries)
      - ``{"items": [{...}, ...], ...}``  (object with an ``items`` array)
      - ``{...}``  (single entry object)
    """
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        items = data.get("items")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
        return [data]
    return []


# ── entry validation ────────────────────────────────────────────────


def _make_prefix(filename: str, index: int) -> str:
    return f"  [{filename}] entry #{index + 1}"


def validate_entry(entry: dict[str, Any], index: int, filename: str) -> list[str]:
    """Run all schema checks on a single entry.  Returns a (possibly empty) list of
    human-readable error strings."""
    errors: list[str] = []
    pf = _make_prefix(filename, index)

    # --- 1. required fields: existence + type ---
    bad_fields: set[str] = set()
    for field, expected_type in REQUIRED_FIELDS.items():
        if field not in entry:
            errors.append(f"{pf}: missing required field '{field}'")
            bad_fields.add(field)
        elif not isinstance(entry[field], expected_type):
            actual = type(entry[field]).__name__
            errors.append(
                f"{pf}: field '{field}' expected {expected_type.__name__}, got {actual}"
            )
            bad_fields.add(field)

    # --- 2. id format --------------------------------------------------
    if "id" not in bad_fields:
        raw_id = str(entry["id"])
        if not _ID_PATTERN.match(raw_id):
            errors.append(
                f"{pf}: invalid id '{raw_id}' (expected {{source}}-{{YYYYMMDD}}-{{NNN}}, "
                f"e.g. github-20260317-001)"
            )

    # --- 3. status enum ------------------------------------------------
    if "status" not in bad_fields:
        raw_status = entry["status"]
        if raw_status not in VALID_STATUSES:
            errors.append(
                f"{pf}: invalid status '{raw_status}' "
                f"(must be one of {sorted(VALID_STATUSES)})"
            )

    # --- 4. source_url format ------------------------------------------
    if "source_url" not in bad_fields:
        raw_url = str(entry["source_url"])
        if not _URL_PATTERN.match(raw_url):
            errors.append(f"{pf}: invalid source_url '{raw_url}'")

    # --- 5. summary length ---------------------------------------------
    if "summary" not in bad_fields:
        raw_summary = str(entry["summary"])
        if len(raw_summary) < MIN_SUMMARY_LEN:
            errors.append(
                f"{pf}: summary too short ({len(raw_summary)} chars, min {MIN_SUMMARY_LEN})"
            )

    # --- 6. tags count -------------------------------------------------
    if "tags" not in bad_fields:
        raw_tags: list[Any] = entry["tags"]  # type guaranteed by check above
        if len(raw_tags) < 1:
            errors.append(f"{pf}: tags must have at least 1 item")

    # --- 7. optional: score (1-10) -------------------------------------
    if "score" in entry:
        score = entry["score"]
        if not isinstance(score, (int, float)) or isinstance(score, bool):
            errors.append(f"{pf}: score must be a number, got {type(score).__name__}")
        elif not (SCORE_MIN <= score <= SCORE_MAX):
            errors.append(f"{pf}: score {score} out of range ({SCORE_MIN}-{SCORE_MAX})")

    # --- 8. optional: audience enum ------------------------------------
    if "audience" in entry:
        audience = entry["audience"]
        if audience not in VALID_AUDIENCES:
            errors.append(
                f"{pf}: audience '{audience}' must be one of {sorted(VALID_AUDIENCES)}"
            )

    return errors


# ── per-file validation ─────────────────────────────────────────────


def validate_file(filepath: Path) -> tuple[list[str], int]:
    """Validate one JSON file.

    Returns ``(errors, entry_count)`` — ``entry_count`` is 0 if the file
    could not be parsed or contained no entry dicts.
    """
    errors: list[str] = []
    data = parse_json(filepath)

    if data is None:
        errors.append(f"[{filepath.name}] FAIL: unable to parse JSON")
        return errors, 0

    entries = extract_entries(data)
    if not entries:
        errors.append(
            f"[{filepath.name}] FAIL: no valid entries found "
            f"(expected JSON object or array)"
        )
        return errors, 0

    for i, entry in enumerate(entries):
        errors.extend(validate_entry(entry, i, filepath.name))

    return errors, len(entries)


# ── main / CLI ──────────────────────────────────────────────────────


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'s' if n != 1 else ''}"


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(
            "Usage: python hooks/validate_json.py <json_file|pattern> [...]",
            file=sys.stderr,
        )
        return 1

    files = expand_files(argv[1:])
    if not files:
        print("Error: no JSON files found", file=sys.stderr)
        return 1

    all_errors: list[str] = []
    total_files = 0
    total_entries = 0
    passed_files = 0
    passed_entries = 0

    for filepath in files:
        total_files += 1
        file_errors, entry_count = validate_file(filepath)
        total_entries += entry_count

        if file_errors:
            all_errors.extend(file_errors)
        else:
            passed_files += 1
            passed_entries += entry_count

    # --- output ---
    if all_errors:
        print("\n".join(all_errors))
        print()

    failed_files = total_files - passed_files
    failed_entries = total_entries - passed_entries

    print(f"Files scanned:  {total_files}")
    print(f"Entries found:  {total_entries}")
    print(f"Files passed:   {passed_files}")
    print(f"Entries passed: {passed_entries}")

    if failed_files:
        print(f"Files failed:   {failed_files}")
    if failed_entries:
        print(f"Entry errors:   {failed_entries}")

    if all_errors:
        print(f"\nValidation FAILED — {len(all_errors)} {_plural(len(all_errors), 'error')}")
        return 1

    print("\nValidation PASSED — all entries conform to schema")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
