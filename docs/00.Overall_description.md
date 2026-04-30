## Project Structure & File Design for `sophia_learner`

This document describes the overall project structure, the plan for key files, database structure, security implementations and configurable parameters of the project.

## 1. Project Root Structure

```
sophia_learner/
├── README.md
├── LICENSE
├── requirements.txt
├── setup.py
├── pyproject.toml
├── .env.example
├── .gitignore
│
├── src/
│   └── sophia_learner/
│       ├── __init__.py
│       ├── main.py                 # Entry point
│       ├── config/
│       │   ├── __init__.py
│       │   ├── settings.py         # Configuration loader
│       │   ├── config.yaml         # User configuration
│       │   └── schema.py           # Config validation
│       │
│       ├── watcher/
│       │   ├── __init__.py
│       │   ├── directory_watcher.py    # Watchdog integration
│       │   ├── event_handler.py        # Custom event handler
│       │   ├── debouncer.py            # delayed hold logic
│       │   └── scheduler.py            # Time-based scheduling
│       │
│       ├── parser/
│       │   ├── __init__.py
│       │   ├── base_parser.py          # Abstract parser class
│       │   ├── doc_parser.py           # .doc (antiword/catdoc)
│       │   ├── docx_parser.py          # .docx (python-docx)
│       │   ├── xls_parser.py           # .xls (xlrd)
│       │   ├── xlsx_parser.py          # .xlsx (openpyxl)
│       │   ├── pdf_parser.py           # .pdf (PyPDF2/pdfplumber)
│       │   └── parser_registry.py      # Extension -> Parser mapping
│       │
│       ├── processor/
│       │   ├── __init__.py
│       │   ├── file_processor.py       # Main processing logic
│       │   ├── version_detector.py     # Parse version from filenames
│       │   ├── conflict_resolver.py    # Version conflict resolution
│       │   └── quarantine.py           # Security quarantine system
│       │
│       ├── ai/
│       │   ├── __init__.py
│       │   ├── base_client.py          # Abstract AI client
│       │   ├── ollama_client.py        # Ollama implementation
│       │   ├── transformers_client.py  # HF transformers
│       │   ├── prompt_templates.py     # Prompt management
│       │   └── training_formatter.py   # Output formatting
│       │
│       ├── db/
│       │   ├── __init__.py
│       │   ├── database.py             # SQLite connection & manager
│       │   ├── models.py               # SQLAlchemy/raw SQL models
│       │   ├── file_tracker.py         # File state operations
│       │   ├── version_tracker.py      # Version tracking
│       │   └── migration.py            # Schema migrations
│       │
│       ├── security/
│       │   ├── __init__.py
│       │   ├── sandbox.py              # Execution isolation
│       │   ├── validator.py            # Content validation
│       │   ├── sanitizer.py            # Strip malicious content
│       │   └── scanner.py              # Virus/malware scanning hook
│       │
│       ├── output/
│       │   ├── __init__.py
│       │   ├── writer.py               # Write training data
│       │   ├── rotator.py              # File rotation & archiving
│       │   └── metrics.py              # Training data metrics
│       │
│       ├── scheduler/
│       │   ├── __init__.py
│       │   ├── time_window.py          # task scheduler / load balancing logic
│       │   ├── rate_limiter.py         # cool-down delay between files
│       │   ├── backfill.py             # Process older files
│       │   └── cron_manager.py         # Optional cron integration
│       │
│       ├── utils/
│       │   ├── __init__.py
│       │   ├── logger.py               # Logging setup
│       │   ├── file_utils.py           # File operations (safe)
│       │   ├── hash_utils.py           # SHA-256 for dedup
│       │   ├── time_utils.py           # Timestamp helpers
│       │   └── retry.py                # Retry decorator
│       │
│       └── cli/
│           ├── __init__.py
│           ├── commands.py             # CLI entry points
│           ├── management_app.py       # Conflict resolution UI
│           └── status_reporter.py      # Show processing status
│
├── tests/
│   ├── __init__.py
│   ├── test_watcher/
│   ├── test_parser/
│   ├── test_processor/
│   ├── test_ai/
│   ├── test_db/
│   ├── test_security/
│   ├── test_scheduler/
│   ├── fixtures/                       # Sample files (doc, pdf, etc.)
│   └── conftest.py                     # Pytest configuration
│
├── scripts/
│   ├── install_systemd.sh              # Install as service
│   ├── init_db.sql                     # Initial database schema
│   └── quarantine_cleanup.sh           # Periodic quarantine purge
│
├── docs/
│   ├── architecture.md
│   ├── api.md
│   ├── security_model.md
│   └── user_guide.md
│
├── data/
│   ├── quarantine/                     # Sandboxed suspicious files
│   │   ├── incoming/
│   │   ├── processed/
│   │   └── rejected/
│   ├── AI-Training/                    # Final output
│   │   ├── training_data.jsonl
│   │   ├── training_data_archive/
│   │   └── metrics/
│   └── sophia.db                       # SQLite database
│
├── logs/
│   ├── sophia_learner.log
│   ├── errors.log
│   ├── security.log
│   └── processing.log
│
├── certs/                              # For TLS if AI client requires
│   └── .gitkeep
│
└── tmp/                                # Temporary extraction space
    └── .gitkeep
```

---

## 2. Key File Descriptions & Interactions

Below is a **detailed blueprint** for each major file – for expanded descriptions, see [Exhaustive_description.md(../Exhaustive_description.md)].

### 2.1 Configuration Layer
| File | Purpose | Key Functions/Classes | Interactions |
|------|---------|----------------------|--------------|
| `config/config.yaml` | User settings | watched_folders, schedule, ai_backend, security | Loaded by `settings.py` |
| `config/settings.py` | Load & validate config | `load_config()`, `validate_config()`, `Settings` dataclass | Uses `schema.py`, passes config to all modules |
| `config/schema.py` | Pydantic/JSON schema validation | `ConfigSchema` class, validation rules | Called by `settings.py` |

### 2.2 Watcher Layer
| File | Purpose | Key Functions/Classes | Interactions |
|------|---------|----------------------|--------------|
| `watcher/directory_watcher.py` | Watchdog observer manager | `DirectoryWatcher` class, `add_folder()`, `start()`, `stop()` | Uses `event_handler.py`, communicates via queue |
| `watcher/event_handler.py` | Custom event handler | `SophiaEventHandler` (inherits `FileSystemEventHandler`), `on_created()`, `on_modified()` | Sends events to `debouncer.py` |
| `watcher/debouncer.py` | 24-hour hold logic | `Debouncer` class, `schedule_file()`, `_is_ready()` | Checks timestamp, releases to `scheduler.py` |
| `watcher/scheduler.py` | Time-window scheduling | `ProcessingScheduler`, `can_process_now()`, `next_available_window()` | Consults config, delays processing |

### 2.3 Parser Layer (Security-first)
| File | Purpose | Key Functions/Classes | Interactions |
|------|---------|----------------------|--------------|
| `parser/base_parser.py` | Abstract parser interface | `BaseParser` ABC, `extract_text()`, `get_metadata()`, `sanitize()` | All parsers inherit this |
| `parser/doc_parser.py` | .doc extraction | `DocParser` class, uses antiword or catdoc (subprocess) | Calls `sanitizer.py` on output |
| `parser/docx_parser.py` | .docx extraction | `DocxParser` class, uses `python-docx` in sandbox | Extracts paragraphs, tables |
| `parser/xls_parser.py` | .xls extraction | `XlsParser` class, uses `xlrd` (disabled external entities) | Extracts cells → text |
| `parser/xlsx_parser.py` | .xlsx extraction | `XlsxParser` class, uses `openpyxl` (read-only mode) | Iterates sheets, rows |
| `parser/pdf_parser.py` | .pdf extraction | `PdfParser` class, uses `pdfplumber` (preferred) or `PyPDF2` | No OCR, text-only, respects security limits |
| `parser/parser_registry.py` | Extension mapping | `ParserRegistry` singleton, `register()`, `get_parser()` | Lazy-loads parsers |

### 2.4 Database Layer (SQLite)
| File | Purpose | Key Functions/Classes | Interactions |
|------|---------|----------------------|--------------|
| `db/database.py` | Connection manager | `Database` class, `get_connection()`, `execute()`, `close()` | All DB operations go through here |
| `db/models.py` | Table schemas as classes | `FileRecord`, `VersionRecord`, `ProcessingLog`, `ConflictRecord` | SQLAlchemy or raw SQL with type hints |
| `db/file_tracker.py` | CRUD for files | `FileTracker` class, `add_file()`, `mark_processed()`, `get_pending_files()` | Used by `file_processor.py` |
| `db/version_tracker.py` | Version management | `VersionTracker`, `register_version()`, `get_version_chain()`, `resolve_conflict()` | Used by `version_detector.py` |
| `db/migration.py` | Schema updates | `run_migrations()`, `Migration` class | Auto-runs on startup |

### 2.5 Security Layer (Critical)
| File | Purpose | Key Functions/Classes | Interactions |
|------|---------|----------------------|--------------|
| `security/sandbox.py` | Isolated execution | `Sandbox` class, `run_in_chroot()` (optional), `resource_limits()` | Wraps parser calls, limits CPU/memory/time |
| `security/validator.py` | Content validation | `validate_file_header()`, `check_mime_type()`, `scan_for_macros()` | Before parsing, rejects known bad files |
| `security/sanitizer.py` | Strip dangerous content | `sanitize_text()`, `remove_embedded_objects()`, `filter_scripts()` | After parsing, before AI |
| `security/scanner.py` | Virus scanning | `VirusScanner` class, `scan_file()`, hooks ClamAV or rkhunter | Optional, can quarantine positives |

### 2.6 Processor Layer
| File | Purpose | Key Functions/Classes | Interactions |
|------|---------|----------------------|--------------|
| `processor/file_processor.py` | Main orchestration | `FileProcessor` class, `process_single_file()`, `_handle_pipeline()` | Glues all components together |
| `processor/version_detector.py` | Parse version from filename | `detect_version()`, `extract_version_pattern()` | Regex patterns like `_v2`, `-1.2.3`, `(2)` |
| `processor/conflict_resolver.py` | Handle version conflicts | `ConflictResolver`, `queue_for_management()`, `apply_user_decision()` | Calls management app or waits |
| `processor/quarantine.py` | Secure storage | `Quarantine` class, `move_to_quarantine()`, `restore()`, `reject()` | Moves suspicious/conflicting files out of watch path |

### 2.7 AI Layer
| File | Purpose | Key Functions/Classes | Interactions |
|------|---------|----------------------|--------------|
| `ai/base_client.py` | AI abstraction | `AIClient` ABC, `process_text()`, `health_check()` | Implemented by Ollama/Transformers |
| `ai/ollama_client.py` | Ollama REST API | `OllamaClient`, `_call_api()`, `_parse_response()` | Uses `httpx` with timeouts |
| `ai/transformers_client.py` | Hugging Face | `TransformersClient`, loads pipeline, batched processing | Requires more memory |
| `ai/prompt_templates.py` | Prompt engineering | `PromptTemplate` class, `render()`, built-in templates | Can be overridden in config |
| `ai/training_formatter.py` | Output formatting | `TrainingFormatter`, `to_jsonl()`, `to_json()`, `validate_output()` | Ensures schema compliance |

### 2.8 Output Layer
| File | Purpose | Key Functions/Classes | Interactions |
|------|---------|----------------------|--------------|
| `output/writer.py` | Write training data | `OutputWriter`, `append_record()`, `flush_buffer()` | Thread-safe, atomic writes |
| `output/rotator.py` | Manage file sizes | `Rotator` class, `rotate_if_needed()`, `archive_old()` | Creates new file every X MB or daily |
| `output/metrics.py` | Statistics | `MetricsCollector`, `log_training_stats()`, `generate_report()` | Tracks tokens, samples, costs |

### 2.9 Scheduler Layer
| File | Purpose | Key Functions/Classes | Interactions |
|------|---------|----------------------|--------------|
| `scheduler/time_window.py` | Daily processing window | `TimeWindow`, `is_within_window()`, `seconds_until_window()` | Checks 5pm–7am custom range |
| `scheduler/rate_limiter.py` | Delay between files | `RateLimiter`, `wait_if_needed()`, `set_delay()` | Default 15 min, user-adjustable |
| `scheduler/backfill.py` | Process existing files | `BackfillProcessor`, `scan_existing_files()`, `enqueue_for_processing()` | Called on first startup |
| `scheduler/cron_manager.py` | Optional cron sync | `CronManager`, `sync_with_cron()` | For external scheduling (optional) |

### 2.10 CLI & Management
| File | Purpose | Key Functions/Classes | Interactions |
|------|---------|----------------------|--------------|
| `cli/commands.py` | CLI entry points | `start()`, `stop()`, `status()`, `conflicts()`, `backfill()` | Uses `argparse` or `click` |
| `cli/management_app.py` | Conflict resolution UI | `ConflictManagementApp`, TUI or CLI prompts | User selects which version to keep |
| `cli/status_reporter.py` | Show system status | `print_status()`, `print_queue()`, `print_metrics()` | Reads from DB and logs |

### 2.11 Utilities
| File | Purpose | Key Functions/Classes |
|------|---------|----------------------|
| `utils/logger.py` | Structured logging | `setup_logging()`, `get_logger()`, `SecurityLogger` |
| `utils/file_utils.py` | Safe file ops | `safe_copy()`, `atomic_write()`, `get_file_size_safe()` |
| `utils/hash_utils.py` | Hashing | `compute_sha256()`, `compute_hash_chunked()` |
| `utils/time_utils.py` | Time helpers | `wait_until()`, `parse_time_window()`, `human_duration()` |
| `utils/retry.py` | Resilience | `retry()`, `retry_async()` decorators with exponential backoff |

---

## 3. Database Schema (SQLite)

```sql
-- files: main tracking
CREATE TABLE files (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL,
    filename TEXT NOT NULL,
    version TEXT,
    sha256 TEXT NOT NULL UNIQUE,
    size_bytes INTEGER,
    mime_type TEXT,
    first_seen TIMESTAMP,
    last_modified TIMESTAMP,
    status TEXT,  -- pending, quarantined, processing, processed, failed, conflicting
    assigned_priority INTEGER DEFAULT 5,
    UNIQUE(path, version)
);

-- versions: version chains
CREATE TABLE versions (
    file_id INTEGER,
    version_number TEXT,
    parent_version TEXT,
    conflict_resolved BOOLEAN DEFAULT 0,
    resolution_choice TEXT,  -- keep, discard, merge
    resolved_by TEXT,
    resolved_at TIMESTAMP,
    FOREIGN KEY(file_id) REFERENCES files(id)
);

-- processing_log: audit trail
CREATE TABLE processing_log (
    id INTEGER PRIMARY KEY,
    file_id INTEGER,
    status TEXT,
    stage TEXT,  -- watcher, parser, ai, output
    message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    retry_count INTEGER DEFAULT 0,
    FOREIGN KEY(file_id) REFERENCES files(id)
);

-- conflicts: pending user decisions
CREATE TABLE conflicts (
    id INTEGER PRIMARY KEY,
    file_group TEXT,  -- logical group of same file with different versions
    versions JSON,    -- list of version strings
    status TEXT,      -- pending, resolved
    created_at TIMESTAMP,
    resolved_at TIMESTAMP
);

-- metrics: performance tracking
CREATE TABLE metrics (
    id INTEGER PRIMARY KEY,
    date DATE,
    files_processed INTEGER,
    tokens_processed INTEGER,
    avg_processing_time_seconds REAL,
    ai_call_count INTEGER
);

-- schedule_log: when processing actually ran
CREATE TABLE schedule_log (
    id INTEGER PRIMARY KEY,
    scheduled_start TIMESTAMP,
    actual_start TIMESTAMP,
    actual_end TIMESTAMP,
    files_processed INTEGER,
    window_name TEXT
);
```

---

## 4. Security Implementation Details

| Threat | Mitigation | Implementation Location |
|--------|-----------|------------------------|
| Malicious macros in .doc/.xls | Strip all VBA, ActiveX | `validator.py` + `sanitizer.py` |
| ZIP bombs / decompression attacks | Limit extraction size (50MB), timeout after 30s | `sandbox.py` |
| Path traversal in filenames | Sanitize filename, reject `../` patterns | `validator.py` |
| XXE in XML-based formats (.docx, .xlsx) | Disable external entities in parsers | `docx_parser.py`, `xlsx_parser.py` |
| SQL injection in DB | Use parameterized queries always | `database.py` |
| Command injection in subprocess | Use `subprocess.run()` with shell=False, whitelist commands | All subprocess calls |
| Memory exhaustion (large PDF) | Stream PDF page-by-page, enforce max pages (1000) | `pdf_parser.py` |
| Unsafe deserialization | Never use `pickle` on untrusted files | All parsers |
| AI prompt injection | Escape input content, use delimiters, validate output | `prompt_templates.py` |

**Quarantine Flow:**
1. File arrives → moved to `data/quarantine/incoming/`
2. Scan & validate → if passes → `quarantine/processed/` → processor
3. If fails → `quarantine/rejected/` with error report

---

## 5. Configuration File Example (`config/config.yaml`)

```yaml
# sophia_learner configuration

watcher:
  watch_folders:
    - /home/user/documents/incoming
    - /shared/team_uploads
  file_extensions:
    - .doc
    - .docx
    - .xls
    - .xlsx
    - .pdf
  hold_hours: 24
  backfill_on_startup: true

scheduler:
  processing_window:
    start: "17:00"  # 5 PM
    end: "07:00"    # 7 AM (next day)
  timezone: "Europe/Berlin"
  delay_between_files_seconds: 900  # 15 minutes
  max_files_per_batch: 10

security:
  sandbox_mode: true
  max_file_size_mb: 100
  max_extraction_time_seconds: 60
  enable_virus_scan: false  # Set true if ClamAV installed
  virus_scan_command: "clamscan --no-summary --infected"
  quarantine_dir: "data/quarantine"
  strip_macros: true
  allowed_mime_types:
    - "application/msword"
    - "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    - "application/vnd.ms-excel"
    - "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    - "application/pdf"

ai:
  backend: "ollama"  # or "transformers"
  ollama:
    url: "http://localhost:11434"
    model: "llama3"
    timeout_seconds: 120
    max_tokens: 2048
    temperature: 0.7
  transformers:
    model_name: "mistralai/Mistral-7B-Instruct-v0.2"
    device: "cuda"  # or "cpu"
    load_in_8bit: true
  prompt_template: "training/prompts/base_prompt.txt"
  output_schema:
    required_fields: ["instruction", "output"]
    optional_fields: ["input", "context"]

output:
  folder: "data/AI-Training"
  format: "jsonl"
  max_file_size_mb: 500
  rotate_daily: true
  compress_archive: true

database:
  path: "data/sophia.db"
  backup_interval_hours: 24
  vacuum_on_startup: false

logging:
  level: "INFO"
  log_dir: "logs"
  max_log_size_mb: 100
  backup_count: 5
  json_format: false  # Set true for structured logging

management:
  conflict_resolution: "manual"  # or "auto_keep_latest"
  management_app_host: "localhost"
  management_app_port: 8080
  notification_command: "notify-send"  # For desktop alerts
```

---

## 6. Execution Flow Diagram

```
Start → Load config → Init DB → Start watcher
         ↓
   Backfill existing files?
         ↓
   (Wait for schedule window)
         ↓
   [Inside window 5pm-7am]
         ↓
   Process queue (at most N files)
         ↓
   For each file:
       - Check hold time (24h)
       - Validate security
       - Parse content
       - Send to AI (if text extracted)
       - Write training data
       - Update DB
         ↓
   Wait delay (15 min)
         ↓
   Repeat until queue empty or window ends
```
