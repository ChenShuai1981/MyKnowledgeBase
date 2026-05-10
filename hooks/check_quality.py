#!/usr/bin/env python3
"""5-dimension quality scoring for knowledge entry JSON files.

Dimensions (weighted total 100):
  1. 摘要质量     (25 pts)  — length + tech keywords
  2. 技术深度     (25 pts)  — article score field (1-10 → 0-25)
  3. 格式规范     (20 pts)  — id / title / source_url / status / timestamp, each 4 pts
  4. 标签精度     (15 pts)  — count + standard tag matching
  5. 空洞词检测   (15 pts)  — deduction per buzzword found

Grades: A ≥ 80, B ≥ 60, C < 60
Exit:  0 when all entries ≥ B; 1 when any entry is C

Usage:
  python hooks/check_quality.py <json_file|pattern> [...]
  python hooks/check_quality.py knowledge/analyzed/*.json
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ═══════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════

# -- scoring caps ------------------------------------------------------

SUMMARY_MAX: float = 25.0
TECH_DEPTH_MAX: float = 25.0
FORMAT_MAX: float = 20.0
TAG_PRECISION_MAX: float = 15.0
BUZZWORD_MAX: float = 15.0

FULL_SCORE: float = 100.0

GRADE_A_MIN: float = 80.0
GRADE_B_MIN: float = 60.0

# -- tech keywords (for summary bonus & depth inference) ---------------

TECH_KEYWORDS: frozenset[str] = frozenset({
    "ai", "llm", "model", "train", "inference", "embedding", "transformer",
    "agent", "rag", "retrieval", "generation", "fine-tun", "token",
    "neural", "deep-learn", "machine-learn", "reinforcement",
    "diffusion", "gan", "encoder", "decoder", "attention",
    "prompt", "context", "open-source", "api", "framework",
    "pipeline", "deploy", "benchmark", "evaluation", "dataset",
    "gpu", "quantiz", "distill", "multimodal", "vision",
    "nlp", "speech", "audio", "robot", "autonomous",
    "python", "rust", "go", "typescript", "protocol",
    "architecture", "latency", "throughput", "orchestr",
})

# -- standard tags for precision scoring -------------------------------

STANDARD_TAGS: frozenset[str] = frozenset({
    "ai", "agent", "ai-agent", "ai-agents", "agent-skills",
    "llm", "machine-learning", "deep-learning", "nlp",
    "computer-vision", "generative-ai", "transformer", "neural-network",
    "ml", "artificial-intelligence", "rag", "mlops",
    "open-source", "api", "framework", "tools", "dev-tools",
    "cli", "library", "model", "training", "inference",
    "embedding", "fine-tuning", "prompt-engineering", "system-prompts",
    "skills", "claude", "claude-code", "openai", "anthropic",
    "coding", "assistant", "automation", "workflow",
    "web-scraping", "browser-automation", "multi-modal",
    "vision", "audio", "speech", "voice", "local-deployment",
    "privacy", "security", "kubernetes", "docker",
    "python", "javascript", "typescript", "rust", "go",
    "frontend", "backend", "database", "memory", "vector-database",
    "evaluation", "benchmark", "testing", "monitoring",
    "chatbot", "search", "retrieval", "recommendation",
    "mcp", "tdd", "multi-channel", "developer-tools", "ux",
})

# -- buzzword blacklists -----------------------------------------------

CN_BUZZWORDS: frozenset[str] = frozenset({
    "赋能", "抓手", "闭环", "打通", "全链路", "底层逻辑",
    "颗粒度", "对齐", "拉通", "沉淀", "强大的", "革命性的",
})

EN_BUZZWORDS: frozenset[str] = frozenset({
    "groundbreaking", "revolutionary", "game-changing", "cutting-edge",
    "disruptive", "best-in-class", "world-class", "unprecedented",
    "paradigm-shift", "next-generation", "state-of-the-art",
    "synergize", "leverage", "holistic", "robust",
})

# -- timestamp field names ---------------------------------------------

TIMESTAMP_FIELDS: frozenset[str] = frozenset({
    "date", "created_at", "updated_at", "timestamp",
    "collected_at", "analysis_date", "published_at", "fetched_at",
})


# ═══════════════════════════════════════════════════════════════════════
# Dataclasses
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class DimensionScore:
    """Single dimension result."""

    name: str
    score: float
    max_score: float
    details: str = ""


@dataclass
class QualityReport:
    """Full quality report for one knowledge entry."""

    file: str
    entry_index: int
    entry_title: str
    dimensions: list[DimensionScore] = field(default_factory=list)
    total: float = 0.0
    grade: str = "C"

    @property
    def max_total(self) -> float:
        return sum(d.max_score for d in self.dimensions)


# ═══════════════════════════════════════════════════════════════════════
# File I/O (shared pattern with validate_json.py)
# ═══════════════════════════════════════════════════════════════════════


def expand_files(paths: list[str]) -> list[Path]:
    """Resolve file paths and glob patterns to a sorted, deduplicated list."""
    seen: dict[str, Path] = {}
    for arg in paths:
        if "*" in arg or "?" in arg or "[" in arg:
            for matched in sorted(Path().glob(arg)):
                seen[str(matched)] = matched
        else:
            p = Path(arg)
            if p.is_file():
                seen[str(p)] = p
            else:
                print(f"Warning: skipping non-existent file: {arg}", file=sys.stderr)
    return list(seen.values())


def parse_json(filepath: Path) -> Any | None:
    """Parse a JSON file; return ``None`` on any failure."""
    try:
        with filepath.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None


def extract_entries(data: Any) -> list[dict[str, Any]]:
    """Extract entry dicts from parsed JSON (array / ``items`` key / single object)."""
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        items = data.get("items")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
        return [data]
    return []


# ═══════════════════════════════════════════════════════════════════════
# Visual helpers
# ═══════════════════════════════════════════════════════════════════════

_BAR_WIDTH: int = 30


def _render_bar(score: float, max_score: float) -> str:
    """Render ``████████████░░░░░░░░░░  20/25`` progress bar."""
    ratio = min(score / max_score, 1.0) if max_score > 0 else 0.0
    filled = int(ratio * _BAR_WIDTH)
    bar = "█" * filled + "░" * (_BAR_WIDTH - filled)

    s = f"{score:.1f}" if score != int(score) else str(int(score))
    m = f"{max_score:.1f}" if max_score != int(max_score) else str(int(max_score))
    return f"{bar}  {s}/{m}"


def _truncate(text: str, width: int = 50) -> str:
    return text if len(text) <= width else text[:width - 3] + "..."


# ═══════════════════════════════════════════════════════════════════════
# Dimension scorers
# ═══════════════════════════════════════════════════════════════════════


def score_summary_quality(entry: dict[str, Any]) -> DimensionScore:
    """Score summary on length (50+ = full, 20+ = basic) + tech keyword bonus."""
    summary = str(entry.get("summary", ""))
    length = len(summary)

    if length >= 50:
        base = 22.0
    elif length >= 20:
        base = 15.0
    else:
        base = 5.0

    lower = summary.lower()
    kw_hits = sum(1 for kw in TECH_KEYWORDS if kw in lower)
    bonus = min(kw_hits * 1.0, 3.0)  # up to +3 bonus
    score = min(base + bonus, SUMMARY_MAX)

    detail = f"len={length}"
    if kw_hits:
        detail += f", +{kw_hits} keywords"
    return DimensionScore(name="摘要质量", score=score, max_score=SUMMARY_MAX, details=detail)


def score_tech_depth(entry: dict[str, Any]) -> DimensionScore:
    """Score tech depth: maps the article ``score`` field (1-10) linearly to 0-25.

    If the ``score`` field is absent, falls back to keyword inference (max 12.5).
    """
    raw = entry.get("score")
    if raw is None:
        # fallback: infer from summary keywords
        summary = str(entry.get("summary", ""))
        lower = summary.lower()
        kw_hits = sum(1 for kw in TECH_KEYWORDS if kw in lower)
        inferred = min(kw_hits * 1.5, 12.5)
        return DimensionScore(
            name="技术深度", score=inferred, max_score=TECH_DEPTH_MAX,
            details=f"no score field, inferred ~{inferred:.1f} from {kw_hits} keywords",
        )

    try:
        numeric = float(raw)
    except (TypeError, ValueError):
        return DimensionScore(name="技术深度", score=0.0, max_score=TECH_DEPTH_MAX,
                              details=f"non-numeric score: {raw}")

    mapped = min(numeric * 2.5, TECH_DEPTH_MAX)
    return DimensionScore(name="技术深度", score=mapped, max_score=TECH_DEPTH_MAX,
                          details=f"raw score={numeric}")


def score_format_compliance(entry: dict[str, Any]) -> DimensionScore:
    """Check 5 fields: id, title, source_url (or url), status, timestamp.

    Each present field earns 4 pts (total 20).
    """
    per_field = 4.0
    checks = [
        ("id", bool(entry.get("id"))),
        ("title", bool(entry.get("title"))),
        ("source_url", bool(entry.get("source_url") or entry.get("url"))),
        ("status", bool(entry.get("status"))),
        ("timestamp", any(entry.get(k) for k in TIMESTAMP_FIELDS)),
    ]

    passed = [name for name, ok in checks if ok]
    missing = [name for name, ok in checks if not ok]
    score = len(passed) * per_field

    detail = f"{len(passed)}/5 fields"
    if missing:
        detail += f" (missing: {', '.join(missing)})"
    return DimensionScore(name="格式规范", score=score, max_score=FORMAT_MAX, details=detail)


def score_tag_precision(entry: dict[str, Any]) -> DimensionScore:
    """Score tag precision: 1-3 standard tags = perfect.

    Handles both ``tags`` and ``topics`` keys.
    """
    tags_raw: list[str] = entry.get("tags") or entry.get("topics") or []
    if not isinstance(tags_raw, list):
        return DimensionScore(name="标签精度", score=0.0, max_score=TAG_PRECISION_MAX,
                              details="tags not a list")

    tags = [str(t).lower() for t in tags_raw]

    if not tags:
        return DimensionScore(name="标签精度", score=0.0, max_score=TAG_PRECISION_MAX,
                              details="no tags")

    standard_count = sum(1 for t in tags if t in STANDARD_TAGS)
    non_standard = len(tags) - standard_count

    if len(tags) <= 3 and non_standard == 0:
        score = TAG_PRECISION_MAX
    elif non_standard == 0:
        # too many tags, but all standard
        score = TAG_PRECISION_MAX - min((len(tags) - 3) * 1.5, 5.0)
    elif standard_count >= 1:
        score = max(TAG_PRECISION_MAX - non_standard * 4.0, 2.0)
    else:
        score = max(TAG_PRECISION_MAX - len(tags) * 5.0, 0.0)

    detail = f"{standard_count}/{len(tags)} standard"
    if non_standard:
        detail += f", {non_standard} non-standard"
    return DimensionScore(name="标签精度", score=score, max_score=TAG_PRECISION_MAX,
                          details=detail)


def score_buzzword_detection(entry: dict[str, Any]) -> DimensionScore:
    """Deduct for each buzzword found in title + summary. Full marks = clean text."""
    title = str(entry.get("title", ""))
    summary = str(entry.get("summary", ""))

    # Chinese: substring match
    text = f"{title} {summary}"
    cn_found = [w for w in CN_BUZZWORDS if w in text]

    # English: word-boundary match
    words: set[str] = set()
    for field in (title, summary):
        words.update(re.findall(r"[a-zA-Z]+", field.lower()))
    en_found = [w for w in EN_BUZZWORDS if w in words]

    total_hits = len(cn_found) + len(en_found)
    deduction = min(total_hits * 3.0, BUZZWORD_MAX)
    score = BUZZWORD_MAX - deduction

    detail = f"{total_hits} buzzword(s)"
    if cn_found:
        detail += f" cn={cn_found}"
    if en_found:
        detail += f" en={en_found}"
    return DimensionScore(name="空洞词检测", score=score, max_score=BUZZWORD_MAX,
                          details=detail)


# ═══════════════════════════════════════════════════════════════════════
# Entry scoring pipeline
# ═══════════════════════════════════════════════════════════════════════

SCORERS = [
    score_summary_quality,
    score_tech_depth,
    score_format_compliance,
    score_tag_precision,
    score_buzzword_detection,
]


def score_entry(entry: dict[str, Any], index: int, filename: str) -> QualityReport:
    """Run all 5 dimension scorers against one entry and compute grade."""
    raw_title = entry.get("title") or entry.get("name") or f"entry-{index + 1}"
    report = QualityReport(
        file=filename,
        entry_index=index,
        entry_title=str(raw_title),
    )

    for scorer in SCORERS:
        dim = scorer(entry)
        report.dimensions.append(dim)

    report.total = sum(d.score for d in report.dimensions)
    if report.total >= GRADE_A_MIN:
        report.grade = "A"
    elif report.total >= GRADE_B_MIN:
        report.grade = "B"
    else:
        report.grade = "C"

    return report


# ═══════════════════════════════════════════════════════════════════════
# Output rendering
# ═══════════════════════════════════════════════════════════════════════

_GRADE_MARKER = {"A": "✦✦✦", "B": "✦✦ ", "C": "✦  "}


def render_report(report: QualityReport) -> str:
    """Format a single QualityReport for terminal display."""
    lines: list[str] = []
    title = _truncate(report.entry_title, 52)

    lines.append(f"\n{'─' * 60}")
    lines.append(f"  [{report.file}] #{report.entry_index + 1}  {title}")
    lines.append(f"{'─' * 60}")

    for dim in report.dimensions:
        bar = _render_bar(dim.score, dim.max_score)
        lines.append(f"  {bar}  {dim.name}")
        if dim.details:
            lines.append(f"    └─ {dim.details}")

    lines.append(f"{'─' * 60}")
    marker = _GRADE_MARKER.get(report.grade, "")
    lines.append(f"  TOTAL: {report.total:.1f}/100   等级: {marker} {report.grade}")
    return "\n".join(lines)


def render_summary(reports: list[QualityReport]) -> str:
    """Format an aggregate summary across all scored entries."""
    total = len(reports)
    if total == 0:
        return "\nNo entries scored."

    a_count = sum(1 for r in reports if r.grade == "A")
    b_count = sum(1 for r in reports if r.grade == "B")
    c_count = sum(1 for r in reports if r.grade == "C")
    avg = sum(r.total for r in reports) / total

    # dimension averages
    dim_sums: list[float] = [0.0] * len(SCORERS)
    dim_names: list[str] = []
    for r in reports:
        for i, dim in enumerate(r.dimensions):
            if i >= len(dim_sums):
                continue
            dim_sums[i] += dim.score
            if len(dim_names) < len(r.dimensions):
                dim_names.append(dim.name)

    lines = [
        f"\n{'═' * 60}",
        "  Quality Check Summary",
        f"{'═' * 60}",
        f"  Entries scanned : {total}",
        f"  Average score   : {avg:.1f} / 100",
        f"  {'─' * 40}",
        f"  Grade A  (≥{GRADE_A_MIN:.0f})   : {a_count:>3}  ✦✦✦",
        f"  Grade B  (≥{GRADE_B_MIN:.0f})   : {b_count:>3}  ✦✦ ",
        f"  Grade C  (<{GRADE_B_MIN:.0f})   : {c_count:>3}  ✦  ",
    ]

    if dim_names:
        lines.append(f"  {'─' * 40}")
        for i, name in enumerate(dim_names):
            dim_avg = dim_sums[i] / total if total else 0
            d_max = reports[0].dimensions[i].max_score if reports else 1
            bar = _render_bar(dim_avg, d_max)
            lines.append(f"  {bar}  {name} (avg)")

    lines.append(f"{'═' * 60}")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(
            "Usage: python hooks/check_quality.py <json_file|pattern> [...]",
            file=sys.stderr,
        )
        return 1

    files = expand_files(argv[1:])
    if not files:
        print("Error: no JSON files found", file=sys.stderr)
        return 1

    all_reports: list[QualityReport] = []

    for filepath in files:
        data = parse_json(filepath)
        if data is None:
            print(f"[{filepath.name}] SKIP: unable to parse JSON", file=sys.stderr)
            continue

        entries = extract_entries(data)
        if not entries:
            print(f"[{filepath.name}] SKIP: no entries found", file=sys.stderr)
            continue

        for i, entry in enumerate(entries):
            report = score_entry(entry, i, filepath.name)
            all_reports.append(report)
            print(render_report(report))

    if not all_reports:
        print("\nNo entries to score.", file=sys.stderr)
        return 1

    print(render_summary(all_reports))

    c_count = sum(1 for r in all_reports if r.grade == "C")
    if c_count > 0:
        print(f"\nQuality check FAILED — {c_count} entry(s) rated C")
        return 1

    print("\nQuality check PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
