#!/usr/bin/env python3
"""
backup_knowledge_base.py
========================
Scans configured project directories, categorizes AI/Copilot/Claude documents
(analysis, design, templates, GitHub prompts, Claude skills, VS Code settings),
and backs them up to an OneDrive knowledge-base folder with a structured layout.

Also generates:
  - manifest.json    — machine-readable index for MCP tool querying
  - knowledge-base-index.md — human-readable index for quick navigation

Usage:
  python backup_knowledge_base.py                        # normal run
  python backup_knowledge_base.py --dry-run              # preview only (no writes)
  python backup_knowledge_base.py --project mercury-services  # one project only
  python backup_knowledge_base.py --verbose              # debug logging
  python backup_knowledge_base.py --config my_config.json

Requirements: Python 3.8+  (no third-party packages needed)
"""

import argparse
import fnmatch
import json
import logging
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def setup_logging(log_file: Optional[str], dry_run: bool) -> logging.Logger:
    logger = logging.getLogger("kb_backup")
    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s [%(levelname)-7s] %(message)s", "%Y-%m-%d %H:%M:%S")

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    if log_file and not dry_run:
        log_path = Path(log_file)
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            fh = logging.FileHandler(log_path, encoding="utf-8")
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(fmt)
            logger.addHandler(fh)
        except Exception as e:
            logger.warning(f"Could not open log file {log_file}: {e}")

    return logger


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config(config_path: str) -> dict:
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(
            f"Config file not found: {config_path}\n"
            "Run from the directory containing kb_config.json, or pass --config <path>."
        )
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    # Strip _comment keys (JSON doesn't support comments natively)
    data = json.loads(raw)
    return data


# ---------------------------------------------------------------------------
# Categorization
# ---------------------------------------------------------------------------

def get_location_category(scan_path_str: str, config: dict) -> Optional[str]:
    """
    Return a fixed category if the scan path begins with a recognised
    dot-folder (.github, .claude, .vscode).  Returns None otherwise.
    """
    normalised = scan_path_str.replace("\\", "/").lower()
    for loc_key, loc_cat in config.get("location_categories", {}).items():
        if loc_key == "_comment":
            continue
        if normalised.startswith(loc_key.lower()):
            return loc_cat
    return None


def read_content_sample(file_path: Path, max_lines: int = 40) -> str:
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = []
            for i, line in enumerate(f):
                if i >= max_lines:
                    break
                lines.append(line)
        return "".join(lines)
    except Exception:
        return ""


def categorize_by_rules(file_path: Path, config: dict, logger: logging.Logger) -> str:
    """
    Categorize a file by filename pattern first, then content keywords.
    Falls back to 'uncategorized'.
    """
    filename = file_path.name.lower()
    categories = {k: v for k, v in config.get("categories", {}).items() if k != "_comment"}
    sorted_cats = sorted(categories.items(), key=lambda x: x[1].get("priority", 99))

    # 1. Filename patterns
    for cat_name, cat_cfg in sorted_cats:
        for pattern in cat_cfg.get("filename_patterns", []):
            if fnmatch.fnmatch(filename, pattern.lower()):
                logger.debug(f"    category={cat_name!r} (filename: {pattern})")
                return cat_name

    # 2. Content keywords
    content = read_content_sample(file_path)
    for cat_name, cat_cfg in sorted_cats:
        for keyword in cat_cfg.get("content_keywords", []):
            if keyword.lower() in content.lower():
                logger.debug(f"    category={cat_name!r} (content: {keyword!r})")
                return cat_name

    uncategorized = config.get("uncategorized_folder", "uncategorized")
    logger.debug(f"    category={uncategorized!r} (no match)")
    return uncategorized


# ---------------------------------------------------------------------------
# Destination path computation
# ---------------------------------------------------------------------------

def get_module_name(scan_path_str: str) -> str:
    """
    'booking/docs'      → 'booking'
    'cloud-sdk-aws/docs'→ 'cloud-sdk-aws'
    '.github'           → ''   (location-based; structure is preserved as-is)
    """
    parts = Path(scan_path_str.replace("\\", "/")).parts
    if parts and not parts[0].startswith("."):
        return parts[0]
    return ""


def compute_destination(
    file_path: Path,
    scan_root: Path,
    project_dest: Path,
    category: str,
    module_name: str,
    is_location_category: bool,
) -> Path:
    """
    For location-based categories (.github, .claude, .vscode):
        <project_dest>/<category>/<relative-path-from-scan-root>
        e.g.  mercury-services/github-prompts/prompts/my.prompt.md

    For content-based categories (analysis, design, templates, uncategorized):
        <project_dest>/<category>/<module>/<relative-path-from-scan-root>
        e.g.  mercury-services/analysis/booking/analysis-v2.md
    """
    relative_to_scan = file_path.relative_to(scan_root)

    if is_location_category:
        return project_dest / category / relative_to_scan
    else:
        if module_name:
            return project_dest / category / module_name / relative_to_scan
        else:
            return project_dest / category / relative_to_scan


# ---------------------------------------------------------------------------
# File copy
# ---------------------------------------------------------------------------

def should_copy(src: Path, dst: Path) -> bool:
    if not dst.exists():
        return True
    return src.stat().st_mtime > dst.stat().st_mtime


def copy_file(src: Path, dst: Path, dry_run: bool, logger: logging.Logger) -> str:
    """
    Returns 'copied', 'skipped', or 'error'.
    """
    if not should_copy(src, dst):
        logger.debug(f"    SKIP (up-to-date): {dst.name}")
        return "skipped"

    action_label = "[DRY RUN] Would copy" if dry_run else "COPY"
    short_dest = "/".join(dst.parts[-4:])  # last 4 path parts for readability
    logger.info(f"    {action_label}: {src.name}  →  .../{short_dest}")

    if dry_run:
        return "copied"

    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return "copied"
    except Exception as e:
        logger.error(f"    ERROR copying {src}: {e}")
        return "error"


# ---------------------------------------------------------------------------
# Project processing
# ---------------------------------------------------------------------------

def process_project(
    project_cfg: dict,
    source_base: Path,
    dest_base: Path,
    config: dict,
    dry_run: bool,
    logger: logging.Logger,
) -> List[dict]:
    project_name = project_cfg["name"]
    project_src  = source_base / project_name
    project_dest = dest_base   / project_name

    if not project_src.exists():
        logger.warning(f"[{project_name}] Source not found — skipping: {project_src}")
        return []

    extensions = tuple(config.get("file_extensions", [".md"]))
    records: List[dict] = []

    logger.info("")
    logger.info("=" * 65)
    logger.info(f"  PROJECT : {project_name}")
    logger.info(f"  Source  : {project_src}")
    logger.info(f"  Dest    : {project_dest}")
    logger.info("=" * 65)

    for scan_entry in project_cfg.get("scan_paths", []):
        if isinstance(scan_entry, str):
            scan_path_str = scan_entry
            recursive = True
        else:
            scan_path_str = scan_entry["path"]
            recursive = scan_entry.get("recursive", True)

        scan_root = project_src / Path(scan_path_str)
        module_name = get_module_name(scan_path_str)
        location_cat = get_location_category(scan_path_str, config)

        if not scan_root.exists():
            logger.warning(f"  Scan path not found (skipping): {scan_root}")
            continue

        logger.info(f"\n  ── {scan_path_str}  [module={module_name or '-'}, loc-cat={location_cat or 'none'}]")

        files = list(scan_root.rglob("*") if recursive else scan_root.glob("*"))
        matching = [f for f in files if f.is_file() and f.suffix.lower() in extensions]

        if not matching:
            logger.info("     (no matching files)")
            continue

        for file_path in sorted(matching):
            logger.debug(f"  Processing: {file_path}")

            if location_cat:
                category = location_cat
            else:
                category = categorize_by_rules(file_path, config, logger)

            is_loc = bool(location_cat)
            dest_path = compute_destination(
                file_path, scan_root, project_dest, category, module_name, is_loc
            )

            action = copy_file(file_path, dest_path, dry_run, logger)

            try:
                mtime = datetime.fromtimestamp(file_path.stat().st_mtime).isoformat()
            except Exception:
                mtime = None

            records.append({
                "project":       project_name,
                "module":        module_name or project_name,
                "scan_path":     scan_path_str,
                "filename":      file_path.name,
                "category":      category,
                "source":        str(file_path),
                "destination":   str(dest_path),
                "relative_path": str(dest_path.relative_to(dest_base)).replace("\\", "/"),
                "last_modified": mtime,
                "backed_up_at":  datetime.now().isoformat(),
                "action":        action,
            })

    return records


# ---------------------------------------------------------------------------
# Manifest + Index generation
# ---------------------------------------------------------------------------

def generate_manifest(
    records: List[dict],
    dest_base: Path,
    dry_run: bool,
    config: dict,
    logger: logging.Logger,
) -> dict:
    """
    Writes manifest.json — structured for MCP tool / agent consumption.

    Query examples:
      "Find all analysis docs for booking module"
      → filter manifest.projects["mercury-services"].files where category=="analysis" and module=="booking"

      "List all github prompts"
      → filter all files where category=="github-prompts"
    """
    categories_present = sorted(set(r["category"] for r in records))
    projects_present   = sorted(set(r["project"]  for r in records))

    by_project: Dict[str, list] = {}
    for r in records:
        by_project.setdefault(r["project"], []).append(r)

    manifest = {
        "schema_version":  "1.0",
        "generated_at":    datetime.now().isoformat(),
        "dry_run":         dry_run,
        "knowledge_base":  str(dest_base),
        "total_files":     len(records),
        "categories":      categories_present,
        "projects":        projects_present,
        "query_hint": (
            "Filter 'files' array by 'project', 'module', 'category', or 'filename'. "
            "'relative_path' is the path relative to knowledge_base root."
        ),
        "files": records,  # flat list — easier for agent queries
        "by_project": {
            proj: {
                "count": len(files),
                "categories": sorted(set(f["category"] for f in files)),
                "files": files,
            }
            for proj, files in by_project.items()
        },
    }

    manifest_path = dest_base / config.get("manifest_filename", "manifest.json")
    if dry_run:
        logger.info(f"\n[DRY RUN] Would write manifest → {manifest_path}")
    else:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        logger.info(f"\nManifest written → {manifest_path}")

    return manifest


def generate_index(
    records: List[dict],
    dest_base: Path,
    dry_run: bool,
    config: dict,
    logger: logging.Logger,
) -> None:
    """Writes a human-readable Markdown index of the entire knowledge base."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    by_project: Dict[str, Dict[str, List[dict]]] = {}
    for r in records:
        by_project.setdefault(r["project"], {}).setdefault(r["category"], []).append(r)

    lines = [
        "# Claude / Copilot Knowledge Base",
        "",
        f"**Last updated:** {now}  ",
        f"**Total documents:** {len(records)}",
        "",
        "> This file is auto-generated by `backup_knowledge_base.py`.  ",
        "> To search or query these documents, load `manifest.json` via your MCP tool.",
        "",
        "---",
        "",
        "## Contents",
        "",
    ]

    # TOC
    for project in sorted(by_project):
        cats = sorted(by_project[project])
        cat_list = ", ".join(cats)
        lines.append(f"- **[{project}](#{project.replace(' ', '-').lower()})** — {cat_list}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Detail sections
    for project in sorted(by_project):
        cats_map = by_project[project]
        total = sum(len(v) for v in cats_map.values())
        lines.append(f"## {project}")
        lines.append("")
        lines.append(f"*{total} document(s)*")
        lines.append("")

        for cat in sorted(cats_map):
            files = cats_map[cat]
            lines.append(f"### {cat.replace('-', ' ').title()} &nbsp;({len(files)})")
            lines.append("")

            for fi in sorted(files, key=lambda x: (x["module"], x["filename"])):
                rel   = fi["relative_path"]
                mdate = (fi.get("last_modified") or "")[:10] or "unknown"
                lines.append(f"- [{fi['filename']}]({rel})")
                lines.append(f"  *module: `{fi['module']}` · modified: {mdate}*")
            lines.append("")

    index_path = dest_base / config.get("index_filename", "knowledge-base-index.md")
    if dry_run:
        logger.info(f"[DRY RUN] Would write index → {index_path}")
    else:
        index_path.parent.mkdir(parents=True, exist_ok=True)
        with open(index_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        logger.info(f"Index written    → {index_path}")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def print_summary(records: List[dict], logger: logging.Logger) -> None:
    copied   = sum(1 for r in records if r["action"] == "copied")
    skipped  = sum(1 for r in records if r["action"] == "skipped")
    errors   = sum(1 for r in records if r["action"] == "error")

    by_cat: Dict[str, int] = {}
    for r in records:
        by_cat[r["category"]] = by_cat.get(r["category"], 0) + 1

    logger.info("")
    logger.info("=" * 65)
    logger.info("  SUMMARY")
    logger.info("=" * 65)
    logger.info(f"  Total files scanned : {len(records)}")
    logger.info(f"  Copied (new/updated): {copied}")
    logger.info(f"  Skipped (up-to-date): {skipped}")
    if errors:
        logger.info(f"  Errors              : {errors}  ← check log for details")
    logger.info("")
    logger.info("  By category:")
    for cat, count in sorted(by_cat.items(), key=lambda x: -x[1]):
        logger.info(f"    {cat:<28} {count:>4} file(s)")
    logger.info("=" * 65)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backup AI knowledge-base documents from project dirs to OneDrive.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--config",   default="kb_config.json",
        help="Path to JSON config file (default: kb_config.json in current dir)",
    )
    parser.add_argument(
        "--dry-run",  action="store_true",
        help="Preview what would be copied without making any changes",
    )
    parser.add_argument(
        "--project",  metavar="NAME",
        help="Process only this project (must match a 'name' in config)",
    )
    parser.add_argument(
        "--verbose",  action="store_true",
        help="Enable debug-level logging",
    )
    args = parser.parse_args()

    # --- Load config ---
    try:
        config = load_config(args.config)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    # --- Setup logging ---
    log_file = config.get("log_file")
    logger   = setup_logging(log_file, dry_run=args.dry_run)
    if args.verbose:
        for h in logger.handlers:
            h.setLevel(logging.DEBUG)

    if args.dry_run:
        logger.info("┌─────────────────────────────────────────────────┐")
        logger.info("│          DRY RUN MODE  — no files written        │")
        logger.info("└─────────────────────────────────────────────────┘")

    logger.info(f"Config          : {Path(args.config).resolve()}")
    logger.info(f"Source base     : {config['source_base']}")
    logger.info(f"Destination base: {config['destination_base']}")

    source_base = Path(config["source_base"])
    dest_base   = Path(config["destination_base"])

    # --- Process projects ---
    all_records: List[dict] = []

    for project_cfg in config.get("projects", []):
        if not project_cfg.get("enabled", True):
            logger.info(f"\nSkipping disabled project: {project_cfg['name']}")
            continue
        if args.project and project_cfg["name"] != args.project:
            continue

        records = process_project(
            project_cfg, source_base, dest_base, config, args.dry_run, logger
        )
        all_records.extend(records)

    if not all_records:
        logger.warning("No files found. Check your source paths and config.")
        sys.exit(0)

    # --- Generate outputs ---
    generate_manifest(all_records, dest_base, args.dry_run, config, logger)
    generate_index(all_records, dest_base, args.dry_run, config, logger)
    print_summary(all_records, logger)


if __name__ == "__main__":
    main()
