# Comprehensive Summary: Sophia Learner Framework Development

This summary captures **all decisions, requirements, architecture, documentation, and next steps** from our conversation. You can use this to continue in a new conversation without losing context.

---

## 1. Project Identity

**Name:** `sophia_learner`  
**Purpose:** Automated framework that watches folders, extracts text/structured data from documents, sends content to a **local AI**, and generates AI training data saved to an output folder.

**Key traits:**
- Runs on **local Linux** (Ubuntu/Debian/RHEL)
- Security-first: sandboxed parsing, macro stripping, optional virus scan, quarantine
- Handles versioned files and conflicts via a **management app**
- Uses **SQLite** for state (not JSON)
- **Scheduled processing:** user-defined window (e.g., 5 PM–7 AM) with configurable delay between files (e.g., 15 min)
- **24‑hour hold** before processing any new file
- Backfill: processes older files already present when service starts

---

## 2. Supported File Formats (Phase 1)

| Format | Parser Library | Security Notes |
|--------|----------------|----------------|
| `.doc` | antiword / catdoc (subprocess) | no macros, sandboxed |
| `.docx` | `python-docx` | read‑only, external entities disabled |
| `.xls` | `xlrd` (formatting_info=False) | no macro execution |
| `.xlsx` | `openpyxl` (read_only=True) | data only, no formulas executed |
| `.pdf` | `pdfplumber` (primary), `PyPDF2` (fallback) | text only, no OCR, page‑by‑page streaming |

No OCR, no image extraction – only text and numeric data.

---

## 3. Technology Stack

| Layer | Technology | Version / Notes |
|-------|------------|----------------|
| Language | Python | 3.10+ |
| File watching | `watchdog` | uses inotify (Linux) |
| Configuration | YAML + Pydantic | schema validation |
| Database | SQLite | ACID, stored in `data/sophia.db` |
| Logging | Python + RotatingFileHandler | structured logs |
| Parsing | see libraries above | all open‑source |
| AI Backend | Ollama (primary) or Hugging Face Transformers | local only, no external API |
| Output format | JSON Lines (`.jsonl`) | extensible schema |
| Sandboxing | `resource` + `multiprocessing` | CPU/time/memory limits |
| CLI | `click` + `rich` | also systemd service |

**System dependencies (install via apt/dnf):** antiword, catdoc, libmagic1, clamav (optional)

---

## 4. High‑Level Processing Pipeline

1. **Watch** – `watchdog` detects file creation / move / modification  
2. **Hold** – 24‑hour debounce (timer resets on edits)  
3. **Security** – magic bytes, MIME, macro scan, virus scan (optional) → quarantine if suspicious  
4. **Extract** – select parser, run in sandbox (CPU/ mem/ timeout limits)  
5. **Sanitize** – strip null bytes, control chars, scripts, macros  
6. **Version detection** – regex patterns (`_v2`, `-1.5`, `(3)`) → group logical files  
7. **Conflict resolution** – manual (management app) or auto‑keep‑latest  
8. **AI processing** – send text to local LLM (Ollama/Transformers) with prompt template  
9. **Output** – append training samples to JSONL file, rotate daily or by size (500 MB)  
10. **State update** – SQLite records every step (audit trail)

---

## 5. Project Structure (Condensed)

```
sophia_learner/
├── src/sophia_learner/
│   ├── config/            settings, schema, config.yaml
│   ├── watcher/           directory_watcher, event_handler, debouncer, scheduler
│   ├── parser/            base_parser, doc/docx/xls/xlsx/pdf_parser, registry
│   ├── processor/         file_processor, version_detector, conflict_resolver, quarantine
│   ├── ai/                base_client, ollama_client, transformers_client, prompt_templates, training_formatter
│   ├── db/                database, models, file_tracker, version_tracker, migration
│   ├── security/          sandbox, validator, sanitizer, scanner
│   ├── output/            writer, rotator, metrics
│   ├── scheduler/         time_window, rate_limiter, backfill, cron_manager
│   ├── cli/               commands, management_app, status_reporter
│   └── utils/             logger, file_utils, hash_utils, time_utils, retry
├── tests/                 (planned)
├── docs/                  README.md, technology_description.md, future_proof.md
├── data/                  quarantine/, AI-Training/, sophia.db
├── logs/                  sophia_learner.log, security.log, errors.log
└── scripts/               systemd install, init_db.sql, quarantine_cleanup.sh
```

---

## 6. Exhaustive Function & Class Inventory

In the conversation we produced a **complete line‑by‑line specification** of every function, class, global variable, input/output types, dependencies (internal/external), and restrictions.

**Key highlights:**
- **Settings** dataclasses (WatcherConfig, SchedulerConfig, SecurityConfig, AIConfig, OutputConfig, DatabaseConfig, LoggingConfig, ManagementConfig)
- **Database** methods: `execute()`, `fetchone()`, `fetchall()`, `backup()`, `vacuum()`
- **FileTracker** CRUD: `add_file()`, `get_pending_files()`, `update_file_status()`
- **VersionTracker** methods: `register_version()`, `detect_conflict()`, `resolve_conflict()`
- **Debouncer** – 24‑hour hold using `threading.Timer`
- **Sandbox** – `run_in_sandbox()` with resource limits, timeouts
- **Parsers** – each implements `extract_text()` and `get_metadata()`
- **AIClient** – abstract, with Ollama and Transformers implementations
- **FileProcessor** – orchestrates the entire pipeline
- **OutputWriter** – thread‑safe, atomic append, auto‑rotation
- **TimeWindow** – `is_within_window()`, `get_next_window_start()`
- **RateLimiter** – enforces delay between files
- **CLI commands** – `start`, `stop`, `status`, `conflicts`, `backfill`, `metrics`

The full function list is too long to repeat here, but it is **preserved in the conversation history** – you can refer back to it when writing code.

---

## 7. Documentation Created

We wrote three documents (already formatted for your project):

### a) `README.md`
- General description, quick start, requirements, license, security highlights.

### b) `technology_description.md`
- Deep architectural review: how scanning, holding, sanitising, AI processing work.
- Complete prerequisites: hardware (min 8 GB RAM, 2 cores), software stack, system dependencies, Ollama setup.
- Security model (defence in depth), quarantine lifecycle, troubleshooting.

### c) `future_proof.md`
- Strategies for extensibility: plugin architecture (entry points), configuration versioning with migrations, training data schema evolution, multi‑model routing, storage backends (S3 etc.), distributed processing (Celery), zero‑trust sandboxing (Firecracker, gVisor), API versioning, event‑driven design, deprecation policy, upgrade paths.
- Risk mitigation: feature flags, adapters for old versions, quarterly review items.

---

## 8. Development Prioritisation Plan

We defined **10 phases** from lowest to highest internal dependency:

1. **Phase 1** – Utilities: `logger`, `hash_utils`, `time_utils`, `retry`, `file_utils`, `schema`  
2. **Phase 2** – Security & DB core: `sanitizer`, `database`, `models`, `validator`, `sandbox`  
3. **Phase 3** – Tracking: `file_tracker`, `version_tracker`, `time_window`, `rate_limiter`  
4. **Phase 4** – Parsers (external libs)  
5. **Phase 5** – AI layer (base client, Ollama, Transformers, templates, formatter)  
6. **Phase 6** – Output management (rotator, writer, metrics)  
7. **Phase 7** – Processing core (version_detector, quarantine, backfill, conflict_resolver, file_processor)  
8. **Phase 8** – Watcher & scheduler integration (debouncer, event_handler, directory_watcher, cron_manager)  
9. **Phase 9** – CLI & management (status_reporter, management_app, commands, main)  
10. **Phase 10** – Configuration loader (`settings.py`) and end‑to‑end tests

You can start coding from **Phase 1** and work upward.

---

## 9. Configuration Example (Abridged)

```yaml
watcher:
  watch_folders: ["/home/user/incoming"]
  hold_hours: 24
scheduler:
  processing_window: {start: "17:00", end: "07:00"}
  delay_between_files_seconds: 900
security:
  sandbox_mode: true
  max_file_size_mb: 100
  strip_macros: true
ai:
  backend: ollama
  ollama: {model: "llama3.2:3b", url: "http://localhost:11434"}
output:
  folder: "data/AI-Training"
  format: jsonl
database:
  path: "data/sophia.db"
```

---

## 10. Next Steps (To Continue in a New Conversation)

When you open a **new conversation**, you can simply paste this summary and then decide:

- **Option A:** Start coding Phase 1 (utility modules).  
- **Option B:** Generate more documentation (e.g., `user_guide.md`, `security_model.md`, `api.md`).  
- **Option C:** Refine the architecture or add new requirements (e.g., support for more file formats, different AI backends, etc.).  

**We stopped after creating `future_proof.md` – no code was written yet.** The function specifications are ready and can be used as a blueprint.

---

## 11. Critical Points to Remember

- **24‑hour hold** – Implemented in `debouncer.py` with threading timers.  
- **Version conflict resolution** – CLI/TUI management app to choose which version to keep.  
- **SQLite only** – No JSON state file.  
- **Processing schedule** – User‑defined daily window; files wait outside window.  
- **Delay between files** – Default 15 min, configurable.  
- **Security** – Sandbox every parser call; strip macros; quarantine suspicious files; optional ClamAV.  
- **AI runs locally** – Never send data to external APIs.  
- **Output format** – JSONL with versioned schema.

---

This summary contains **everything** we discussed. You can now start a fresh conversation, paste this text, and we can resume coding or documentation exactly where we left off.
