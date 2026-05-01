# Claude/Copilot Knowledge Base — Backup & Categorization Tool

A lightweight Python script that scans your project directories for AI-related documents
(analysis notes, design specs, GitHub Copilot prompts, Claude skills, VS Code settings)
and backs them up to an organized, categorized folder in your OneDrive — ready to be
queried by Claude, Copilot, or any MCP tool.

---

## What it does

- **Scans** configurable project paths (`.github`, `.claude`, `.vscode`, `*/docs`)
- **Categorizes** each file into one of:
  | Category | What goes here |
  |---|---|
  | `github-prompts` | `.github/**` — Copilot instructions, prompt files |
  | `claude-skills` | `.claude/**` — Claude skill definitions |
  | `vscode-settings` | `.vscode/**` — workspace settings, task definitions |
  | `analysis` | Research, investigation, background docs |
  | `design` | Architecture, specs, ADRs, solution designs |
  | `templates` | Reusable scaffolds and boilerplate docs |
  | `uncategorized` | Everything else |
- **Copies** only new or changed files (incremental backup)
- **Generates** `manifest.json` — a machine-readable index for MCP/agent queries
- **Generates** `knowledge-base-index.md` — a human-readable table of contents
- **Logs** every run to `_logs/backup.log` in the knowledge base folder

---

## Destination folder layout

```
OneDrive/claude-workspace/
├── mercury-services/
│   ├── github-prompts/          ← from .github/**
│   │   ├── copilot-instructions.md
│   │   └── prompts/
│   │       └── refactor.prompt.md
│   ├── claude-skills/           ← from .claude/**
│   ├── vscode-settings/         ← from .vscode/**
│   ├── analysis/
│   │   └── booking/
│   │       └── booking-analysis-v2.md
│   ├── design/
│   │   └── oceanschedules/
│   │       └── architecture.md
│   ├── templates/
│   └── uncategorized/
├── mercury-services-commons/
│   └── ...
├── _logs/
│   └── backup.log
├── manifest.json                ← MCP query target
└── knowledge-base-index.md      ← Human TOC
```

---

## Prerequisites

- **Python 3.8+** — no third-party packages needed (standard library only)
- Access to both the source project directories and the OneDrive destination folder

Verify Python is available:
```powershell
python --version
```

---

## Setup

1. **Create a tools folder** for the script (recommended location):
   ```
   C:\Users\arijit.kundu\projects\_kb-tools\
   ```

2. **Copy these three files** into that folder:
   ```
   backup_knowledge_base.py
   kb_config.json
   kb_scheduler.xml        (for Task Scheduler setup)
   ```

3. **Verify config paths** in `kb_config.json`:
   - `source_base` and `destination_base` are already set to your paths
   - Enable/disable projects with `"enabled": true/false`
   - Add new `scan_paths` entries to any project as your codebase grows

---

## Running manually

Open PowerShell or Git Bash in the `_kb-tools` folder:

```powershell
# Normal run (copies new/changed files)
python backup_knowledge_base.py

# Preview only — see what would be copied without writing anything
python backup_knowledge_base.py --dry-run

# Process only one project
python backup_knowledge_base.py --project mercury-services

# Verbose debug output
python backup_knowledge_base.py --verbose

# Use a config file in a different location
python backup_knowledge_base.py --config "C:\path\to\my_config.json"
```

---

## Scheduling (daily automatic backup)

### Install via Task Scheduler (recommended)

Open **PowerShell as Administrator** and run:

```powershell
schtasks /Create /XML "C:\Users\arijit.kundu\projects\_kb-tools\kb_scheduler.xml" /TN "KnowledgeBaseBackup" /F
```

The task will:
- Run every day at **08:30 AM**
- Also run **2 minutes after you log in** (to catch missed runs after restarts)
- Run on next available time if the machine was off at the scheduled time

### Useful Task Scheduler commands

```powershell
# Run immediately
schtasks /Run /TN "KnowledgeBaseBackup"

# Check status
schtasks /Query /TN "KnowledgeBaseBackup" /FO LIST

# Disable (without deleting)
schtasks /Change /TN "KnowledgeBaseBackup" /DISABLE

# Re-enable
schtasks /Change /TN "KnowledgeBaseBackup" /ENABLE

# Remove
schtasks /Delete /TN "KnowledgeBaseBackup" /F
```

### Change the daily run time

Edit `kb_scheduler.xml` and change:
```xml
<StartBoundary>2026-05-01T08:30:00</StartBoundary>
```
to your preferred time, then re-import with the `/Create /F` command above.

---

## Extending the config

### Add a new project module's docs folder

In `kb_config.json`, find the project and add to `scan_paths`:
```json
{ "path": "my-new-module/docs", "recursive": true }
```

### Enable a new project

Set `"enabled": true` for any of the pre-configured projects (`appianway`, `inttra-ai`, `mft-s3-aqua-appia`),
or add a new entry:
```json
{
  "name": "my-new-project",
  "enabled": true,
  "description": "My new service",
  "scan_paths": [
    { "path": ".github", "recursive": true },
    { "path": ".claude", "recursive": true },
    { "path": "my-module/docs", "recursive": true }
  ]
}
```

### Add a new category

In the `categories` block, add:
```json
"runbook": {
  "priority": 4,
  "filename_patterns": ["*runbook*", "*playbook*", "*ops-guide*"],
  "content_keywords": ["## Runbook", "## On-Call Steps", "# Playbook"]
}
```

---

## Querying the knowledge base

### From Claude (Cowork/Chat)

Point Claude at your `manifest.json` or `knowledge-base-index.md`:

> "Read `C:\Users\arijit.kundu\OneDrive - WiseTech Global\claude-workspace\manifest.json`
> and find all analysis documents for the booking module."

Or:

> "Before making changes to the oceanschedules module, review any design documents
> in my knowledge base at `C:\Users\arijit.kundu\OneDrive - WiseTech Global\claude-workspace`."

### From GitHub Copilot

Add this to `.github/copilot-instructions.md` in each project:

```markdown
## Knowledge Base
Before proposing architectural changes or writing new analysis, always check the
knowledge base at:
  C:\Users\arijit.kundu\OneDrive - WiseTech Global\claude-workspace\manifest.json

Use the `module` and `category` fields to find relevant prior art.
```

### Via MCP filesystem tool

Configure your MCP filesystem server to read:
```
C:\Users\arijit.kundu\OneDrive - WiseTech Global\claude-workspace
```

Then agents can call:
- `read_file("manifest.json")` to get the full structured index
- `read_file("knowledge-base-index.md")` for a quick overview
- `read_file("mercury-services/analysis/booking/my-doc.md")` to read a specific doc

---

## Categorization logic

Files are categorized in this order of precedence:

1. **Location** — if the scan path starts with `.github`, `.claude`, or `.vscode`,
   the location category wins regardless of filename or content.

2. **Filename pattern** — checked against `categories[*].filename_patterns` (fnmatch, case-insensitive),
   in order of `priority`.

3. **Content keywords** — the first 40 lines of the file are scanned for markdown headings
   defined in `categories[*].content_keywords`.

4. **Fallback** — file goes to `uncategorized/`.

To override a file's category without renaming it, add it to a custom scan path with
a dedicated location entry in `location_categories`.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `Config file not found` | Run from the `_kb-tools` folder, or pass `--config <full path>` |
| Source path not found | Check the project exists at `source_base/project_name` |
| Files not being categorized correctly | Use `--verbose` to see which rule (or lack of) matched |
| OneDrive folder not writable | Make sure OneDrive sync is active and the folder exists |
| Task Scheduler not running | Open Task Scheduler UI → check Last Run Result (0 = success) |

Logs are written to:
```
C:\Users\arijit.kundu\OneDrive - WiseTech Global\claude-workspace\_logs\backup.log
```

---

## Roadmap / future ideas

- **Git-aware backup** — skip files already committed to source control, focus on uncommitted AI artefacts
- **Semantic search index** — generate embeddings for each document so agents can do similarity search
- **Auto-register with MCP** — write an MCP config snippet pointing to `manifest.json` after each backup
- **Copilot workspace file generation** — auto-write `.github/copilot-workspace.yml` referencing key design docs
- **OneDrive delta sync** — use OneDrive API to detect remote changes rather than mtime comparison
