#!/usr/bin/env python3
"""
Walk the repository and write a single markdown file with all text sources concatenated
for upload to another LLM. Re-run after code changes.

Default output: README_LLM_CONTEXT.md (repo root).

Usage (from repo root):
  python3 scripts/build_llm_context.py
  python3 scripts/build_llm_context.py -o OTHER.md
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Directory path fragments: if any appears as a path segment, skip the file.
SKIP_DIR_PARTS = frozenset(
    {
        ".git",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        "kicad-symbols",
        "kicad-footprints",
        ".tscircuit-home",
    }
)

# Skip if path contains this segment (nested .git in submodules).
SKIP_PATH_CONTAINS = (
    "/tscircuit/.git/",
    "-backups/",  # KiCad backup zips folder (zips skipped by ext anyway)
)

SKIP_NAMES = frozenset(
    {
        ".DS_Store",
        "fp-info-cache",
    }
)

SKIP_EXTENSIONS = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".ico",
        ".pdf",
        ".zip",
        ".woff",
        ".woff2",
        ".ttf",
        ".eot",
        ".bin",
        ".exe",
        ".so",
        ".dylib",
        ".dll",
        ".step",
        ".stp",
        ".wasm",
        ".pile",
        ".pack",
        ".pyc",
        ".pyo",
        ".lck",
    }
)

# Max single file size (bytes); larger files get a placeholder only.
MAX_BYTES = 512 * 1024


def should_skip(path: Path, rel: str) -> str | None:
    parts = path.parts
    for p in parts:
        if p in SKIP_DIR_PARTS:
            return f"directory segment {p!r}"
    for frag in SKIP_PATH_CONTAINS:
        if frag in rel.replace("\\", "/"):
            return f"path contains {frag!r}"
    if path.name in SKIP_NAMES:
        return f"name {path.name!r}"
    suf = path.suffix.lower()
    if suf in SKIP_EXTENSIONS:
        return f"extension {suf!r}"
    return None


def iter_candidate_files() -> list[Path]:
    """Walk the tree with directory pruning (avoids scanning node_modules, .git, etc.)."""
    out: list[Path] = []
    root = str(REPO_ROOT)
    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        # Prune before descending — modify dirnames in place
        keep: list[str] = []
        for d in dirnames:
            if d in SKIP_DIR_PARTS:
                continue
            if d == ".git":
                continue
            keep.append(d)
        dirnames[:] = keep

        for name in filenames:
            p = Path(dirpath) / name
            rel = p.relative_to(REPO_ROOT).as_posix()
            if should_skip(p, rel):
                continue
            if p.is_file():
                out.append(p)
    out.sort(key=lambda x: x.as_posix().lower())
    return out


def read_text_safe(path: Path) -> tuple[str | None, str | None]:
    try:
        raw = path.read_bytes()
    except OSError as e:
        return None, f"read error: {e}"
    if len(raw) > MAX_BYTES:
        return None, f"skipped (>{MAX_BYTES} bytes)"
    if b"\x00" in raw[:8192]:
        return None, "skipped (binary null in header)"
    try:
        return raw.decode("utf-8"), None
    except UnicodeDecodeError:
        try:
            return raw.decode("utf-8", errors="replace"), None
        except Exception as e:  # pragma: no cover
            return None, f"decode error: {e}"


def main() -> None:
    ap = argparse.ArgumentParser(description="Concatenate repo text into one markdown file.")
    ap.add_argument(
        "-o",
        "--output",
        type=Path,
        default=REPO_ROOT / "README_LLM_CONTEXT.md",
        help="Output path (default: README_LLM_CONTEXT.md in repo root)",
    )
    args = ap.parse_args()
    out_path: Path = args.output.resolve()

    lines: list[str] = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines.append("# Full repository context (machine-generated)\n")
    lines.append(f"Generated: **{now}**  \n")
    lines.append(f"Repo root: `{REPO_ROOT}`\n\n")
    lines.append("## What is included\n\n")
    lines.append(
        "- Source code, config, docs, JSON data, KiCad text artifacts under the repo, "
        "excluding the directories and file types listed below.\n\n"
    )
    lines.append("## What is excluded\n\n")
    lines.append("- `.git/`, `node_modules/`, `__pycache__/`, `.venv/`, `venv/`\n")
    lines.append("- `KICAD_Library/kicad-symbols/` and `kicad-footprints/` (vendored libraries; huge)\n")
    lines.append("- `tscircuit/.git/` and `.tscircuit-home/` caches\n")
    lines.append(
        "- Binaries and assets: images, fonts, `.zip`, `.pdf`, `.so`, `.step`, KiCad `.lck`, etc.\n"
    )
    lines.append(f"- Files larger than **{MAX_BYTES // 1024} KiB** (placeholder only)\n")
    lines.append("- `.DS_Store`, `fp-info-cache`\n\n")
    lines.append("---\n\n")

    candidates = iter_candidate_files()
    skipped: list[tuple[str, str]] = []
    included = 0

    for path in candidates:
        rel = path.relative_to(REPO_ROOT).as_posix()
        text, err = read_text_safe(path)
        if err:
            skipped.append((rel, err))
            continue
        assert text is not None
        lines.append(f"\n\n## FILE: `{rel}`\n\n")
        # 6-backtick fence so inner ``` from markdown/MDX in the repo does not terminate the block.
        lines.append("``````\n")
        lines.append(text)
        if not text.endswith("\n"):
            lines.append("\n")
        lines.append("``````\n")
        included += 1

    if skipped:
        lines.append("\n\n---\n\n## Skipped files (summary)\n\n")
        for rel, reason in skipped:
            lines.append(f"- `{rel}` — {reason}\n")

    lines.append(f"\n\n---\n\n*End of dump: **{included}** files included, **{len(skipped)}** skipped.*\n")

    out_path.write_text("".join(lines), encoding="utf-8")
    print(f"Wrote {out_path} ({included} files, {len(skipped)} skipped)")


if __name__ == "__main__":
    main()
