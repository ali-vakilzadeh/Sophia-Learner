# Exhaustive Function & Class Reference for `sophia_learner`

This is the **complete technical specification** for every function, class, and global variable, organized by file.

---

## Legend

- **Internal Dependency**: Functions/classes from within `sophia_learner`
- **External Dependency**: Third-party libraries
- **Stdlib**: Python standard library (no install needed)
- **→**: Returns / yields

---

## 1. Configuration Layer

### `src/sophia_learner/config/settings.py`

#### Global Variables
```python
_CONFIG_INSTANCE: Optional[Settings] = None  # Singleton pattern
```

#### Classes

**`Settings`** (dataclass)
- **Purpose**: Hold all validated configuration values
- **Attributes**:
  - `watcher: WatcherConfig`
  - `scheduler: SchedulerConfig`
  - `security: SecurityConfig`
  - `ai: AIConfig`
  - `output: OutputConfig`
  - `database: DatabaseConfig`
  - `logging: LoggingConfig`
  - `management: ManagementConfig`

**`WatcherConfig`** (dataclass)
- Attributes: `watch_folders: List[Path]`, `file_extensions: List[str]`, `hold_hours: int`, `backfill_on_startup: bool`

**`SchedulerConfig`** (dataclass)
- Attributes: `processing_window: Dict[str, str]`, `timezone: str`, `delay_between_files_seconds: int`, `max_files_per_batch: int`

**`SecurityConfig`** (dataclass)
- Attributes: `sandbox_mode: bool`, `max_file_size_mb: int`, `max_extraction_time_seconds: int`, `enable_virus_scan: bool`, `virus_scan_command: str`, `quarantine_dir: Path`, `strip_macros: bool`, `allowed_mime_types: List[str]`

**`AIConfig`** (dataclass)
- Attributes: `backend: Literal["ollama", "transformers"]`, `ollama: Optional[Dict]`, `transformers: Optional[Dict]`, `prompt_template: Path`, `output_schema: Dict`

**`OutputConfig`** (dataclass)
- Attributes: `folder: Path`, `format: Literal["jsonl", "json"]`, `max_file_size_mb: int`, `rotate_daily: bool`, `compress_archive: bool`

**`DatabaseConfig`** (dataclass)
- Attributes: `path: Path`, `backup_interval_hours: int`, `vacuum_on_startup: bool`

**`LoggingConfig`** (dataclass)
- Attributes: `level: str`, `log_dir: Path`, `max_log_size_mb: int`, `backup_count: int`, `json_format: bool`

**`ManagementConfig`** (dataclass)
- Attributes: `conflict_resolution: Literal["manual", "auto_keep_latest"]`, `management_app_host: str`, `management_app_port: int`, `notification_command: Optional[str]`

#### Functions

**`load_config(config_path: Optional[Path] = None) -> Settings`**
- **Purpose**: Load, validate, and return configuration
- **Input**: 
  - `config_path`: Optional custom path (default: `./config/config.yaml`)
- **Output**: `Settings` instance (validated)
- **Restrictions**: File must exist and be valid YAML; raises `ConfigError` if invalid
- **External deps**: `yaml` (PyYAML), `pydantic` for validation
- **Internal deps**: `schema.validate_config()`

**`get_config() -> Settings`** (singleton accessor)
- **Purpose**: Return existing config instance or load default
- **Input**: None
- **Output**: `Settings` instance
- **Restrictions**: None
- **Internal deps**: `_CONFIG_INSTANCE`, `load_config()`

**`reload_config() -> Settings`**
- **Purpose**: Force reload config from disk
- **Input**: None
- **Output**: Fresh `Settings` instance
- **Internal deps**: `load_config()`, updates `_CONFIG_INSTANCE`

---

### `src/sophia_learner/config/schema.py`

#### Classes

**`ConfigSchema`** (Pydantic model)
- **Purpose**: Validate YAML structure against expected schema
- **Fields**: All fields matching `Settings` structure with validation rules
- **Methods**:
  - `validate_watch_folders(cls, v)`: Ensure folders exist and are readable
  - `validate_time_window(cls, v)`: Ensure start != end and format is HH:MM

#### Functions

**`validate_config(config_dict: Dict) -> Dict`**
- **Purpose**: Validate raw config dictionary
- **Input**: `config_dict` from YAML
- **Output**: Validated dictionary (or raises `ValidationError`)
- **External deps**: `pydantic`

**`validate_ai_backend(backend_config: Dict) -> bool`**
- **Purpose**: Check if selected AI backend is available
- **Input**: AI configuration section
- **Output**: `True` if available, `False` otherwise (logs warning)

---

## 2. Database Layer

### `src/sophia_learner/db/database.py`

#### Global Variables
```python
_DB_CONNECTION: Optional[sqlite3.Connection] = None
```

#### Classes

**`Database`** (singleton manager)
- **Purpose**: Manage SQLite connection, connection pooling, thread safety
- **Methods**:

**`__init__(db_path: Path, foreign_keys: bool = True)`**
- **Purpose**: Initialize database manager
- **Input**: Path to DB file, enable foreign keys constraint
- **Internal deps**: None (stdlib only)

**`connect() -> sqlite3.Connection`**
- **Purpose**: Create or return existing connection
- **Output**: SQLite connection object
- **Restrictions**: Thread-safe using `threading.local()`
- **Internal deps**: `_get_connection()`

**`execute(query: str, params: tuple = (), commit: bool = False) -> sqlite3.Cursor`**
- **Purpose**: Execute SQL with parameterized query
- **Input**: SQL query, parameters, auto-commit flag
- **Output**: Cursor object
- **Restrictions**: Always uses parameterized queries (SQL injection safe)
- **Internal deps**: `connect()`

**`executemany(query: str, params_list: List[tuple], commit: bool = False) -> sqlite3.Cursor`**
- **Purpose**: Batch execute same query with multiple parameter sets
- **Internal deps**: `connect()`

**`fetchone(query: str, params: tuple = ()) -> Optional[tuple]`**
- **Purpose**: Execute query and return single row
- **Internal deps**: `execute()`

**`fetchall(query: str, params: tuple = ()) -> List[tuple]`**
- **Purpose**: Execute query and return all rows
- **Internal deps**: `execute()`

**`commit()`** and **`rollback()`**
- **Purpose**: Transaction management
- **Internal deps**: `connect()`

**`close()`**
- **Purpose**: Close connection and clean up
- **Internal deps**: Updates `_DB_CONNECTION`

**`backup(backup_path: Path) -> bool`**
- **Purpose**: Create hot backup of database
- **Output**: `True` if successful
- **Restrictions**: Uses SQLite online backup API

**`vacuum()`**
- **Purpose**: Rebuild database to reclaim space

**`table_exists(table_name: str) -> bool`**
- **Output**: Boolean indicating if table exists

---

### `src/sophia_learner/db/models.py`

#### Classes (Data classes matching SQL schema)

**`FileRecord`**
- Attributes: `id: int`, `path: Path`, `filename: str`, `version: Optional[str]`, `sha256: str`, `size_bytes: int`, `mime_type: str`, `first_seen: datetime`, `last_modified: datetime`, `status: Literal["pending", "quarantined", "processing", "processed", "failed", "conflicting"]`, `assigned_priority: int`
- Methods: `to_dict()`, `from_dict()`

**`VersionRecord`**
- Attributes: `file_id: int`, `version_number: str`, `parent_version: Optional[str]`, `conflict_resolved: bool`, `resolution_choice: Optional[str]`, `resolved_by: Optional[str]`, `resolved_at: Optional[datetime]`

**`ProcessingLog`**
- Attributes: `id: int`, `file_id: int`, `status: str`, `stage: str`, `message: str`, `created_at: datetime`, `retry_count: int`

**`ConflictRecord`**
- Attributes: `id: int`, `file_group: str`, `versions: List[str]`, `status: Literal["pending", "resolved"]`, `created_at: datetime`, `resolved_at: Optional[datetime]`

**`MetricRecord`**
- Attributes: `id: int`, `date: date`, `files_processed: int`, `tokens_processed: int`, `avg_processing_time_seconds: float`, `ai_call_count: int`

**`ScheduleLog`**
- Attributes: `id: int`, `scheduled_start: datetime`, `actual_start: datetime`, `actual_end: datetime`, `files_processed: int`, `window_name: str`

#### Functions

**`create_tables(db: Database)`**
- **Purpose**: Create all tables if they don't exist
- **Input**: Database instance
- **Internal deps**: `Database.execute()`

**`migrate_schema(db: Database, target_version: int)`**
- **Purpose**: Apply schema migrations incrementally
- **Internal deps**: `Database.execute()`, `_get_current_version()`

---

### `src/sophia_learner/db/file_tracker.py`

#### Classes

**`FileTracker`**
- **Purpose**: CRUD operations for file records
- **Dependencies**: `Database` (internal)

**`__init__(db: Database)`**
- **Internal deps**: Stores `self._db`

**`add_file(file_record: FileRecord) -> int`**
- **Purpose**: Insert new file record
- **Output**: New file ID
- **Restrictions**: Raises `IntegrityError` if SHA256 exists
- **Internal deps**: `_db.execute()`

**`get_file_by_path(path: Path, version: Optional[str] = None) -> Optional[FileRecord]`**
- **Internal deps**: `_db.fetchone()`

**`get_file_by_sha256(sha256: str) -> Optional[FileRecord]`**
- **Internal deps**: `_db.fetchone()`

**`get_pending_files(limit: int = 100) -> List[FileRecord]`**
- **Purpose**: Get files with status='pending', ordered by priority and first_seen
- **Internal deps**: `_db.fetchall()`

**`update_file_status(file_id: int, status: str, message: Optional[str] = None)`**
- **Internal deps**: `_db.execute()`

**`file_exists(sha256: str) -> bool`**
- **Internal deps**: `_db.fetchone()`

**`get_failed_files(retry_limit: int = 3) -> List[FileRecord]`**
- **Purpose**: Get files with retry_count < retry_limit and status='failed'
- **Internal deps**: `_db.fetchall()`

**`increment_retry_count(file_id: int)`**
- **Internal deps**: `_db.execute()`

**`get_statistics() -> Dict`**
- **Purpose**: Return counts by status
- **Output**: `{"pending": 5, "processed": 120, "failed": 3, ...}`

---

### `src/sophia_learner/db/version_tracker.py`

#### Classes

**`VersionTracker`**
- **Dependencies**: `Database` (internal)

**Methods:**

**`register_version(file_id: int, version_number: str, parent_version: Optional[str] = None)`**
- **Internal deps**: `_db.execute()`

**`get_version_chain(file_path: Path) -> List[VersionRecord]`**
- **Purpose**: Return all versions of same logical file
- **Internal deps**: `_db.fetchall()`

**`detect_conflict(file_group: str, versions: List[str]) -> Optional[int]`**
- **Purpose**: Check if conflict already exists for this group
- **Output**: Conflict ID or None
- **Internal deps**: `_db.fetchone()`

**`create_conflict(file_group: str, versions: List[str]) -> int`**
- **Output**: New conflict ID
- **Internal deps**: `_db.execute()`

**`resolve_conflict(conflict_id: int, chosen_version: str, resolved_by: str = "user")`**
- **Internal deps**: `_db.execute()`

**`get_pending_conflicts() -> List[ConflictRecord]`**
- **Internal deps**: `_db.fetchall()`

**`mark_version_as_resolved(file_id: int, resolution: str)`**
- **Internal deps**: `_db.execute()`

---

## 3. Watcher Layer

### `src/sophia_learner/watcher/directory_watcher.py`

#### Global Variables
```python
_OBSERVER: Optional[watchdog.observers.Observer] = None
```

#### Classes

**`DirectoryWatcher`**
- **Purpose**: Manages watchdog observers for multiple directories
- **Dependencies**: `watchdog`, `event_handler.SophiaEventHandler` (internal)

**`__init__(event_queue: queue.Queue, config: WatcherConfig)`**
- **Input**: Queue for events, watcher configuration
- **Internal deps**: Stores queue, creates handlers

**`add_watch(path: Path, recursive: bool = True) -> bool`**
- **Purpose**: Start watching a folder
- **Output**: True if successful
- **External deps**: `watchdog.observers.Observer.schedule()`

**`remove_watch(path: Path)`**
- **Internal deps**: `_observer.unschedule()`

**`start()`**
- **Purpose**: Start observer thread
- **External deps**: `observer.start()`

**`stop()`**
- **External deps**: `observer.stop()`, `observer.join()`

**`on_any_event(event)`** (callback)
- **Purpose**: Log all events for debugging
- **Internal deps**: `logger`

---

### `src/sophia_learner/watcher/event_handler.py`

#### Classes

**`SophiaEventHandler(FileSystemEventHandler)`**
- **Purpose**: Handle filesystem events and push to debouncer
- **Dependencies**: `watchdog.events`, `debouncer.Debouncer` (internal)

**`__init__(debouncer: Debouncer, extensions: List[str])`**
- **Internal deps**: Stores debouncer and whitelisted extensions

**`on_created(event)`**
- **Purpose**: File/directory created
- **Restrictions**: Ignores directories, checks extension
- **Internal deps**: `_queue_event()`

**`on_modified(event)`**
- **Purpose**: File modified (for already-tracked files)
- **Internal deps**: `_queue_event()`

**`on_moved(event)`**
- **Purpose**: File moved into watched folder
- **Internal deps**: `_queue_event()`

**`_queue_event(file_path: Path)`**
- **Purpose**: Push event to debouncer if extension matches
- **Internal deps**: `debouncer.add_event()`

**`_is_valid_extension(file_path: Path) -> bool`**
- **Output**: Boolean
- **Internal deps**: Check against `self._extensions`

---

### `src/sophia_learner/watcher/debouncer.py`

#### Classes

**`Debouncer`**
- **Purpose**: Implements 24-hour hold policy and duplicate suppression
- **Dependencies**: `threading`, `time`, `scheduler.ProcessingScheduler` (internal)

**`__init__(hold_hours: int, processing_queue: queue.Queue, scheduler: ProcessingScheduler)`**
- **Internal deps**: Stores hold duration, output queue, scheduler reference

**`add_event(file_path: Path, event_time: datetime)`**
- **Purpose**: Add file to debounce tracking
- **Internal deps**: `_tracker` dict, `_schedule_release()`

**`_schedule_release(file_path: Path, release_time: datetime)`**
- **Purpose**: Schedule file release after hold period using threading.Timer
- **Internal deps**: Uses `threading.Timer`

**`_release_file(file_path: Path)`**
- **Purpose**: Called by timer; checks if still needs processing
- **Internal deps**: Checks existing DB status via `FileTracker`, then `_push_to_processing()`

**`_push_to_processing(file_path: Path)`**
- **Purpose**: Push to processing queue if within schedule window
- **Internal deps**: `scheduler.can_process_now()`, `processing_queue.put()`

**`cancel_file(file_path: Path)`**
- **Purpose**: Cancel pending release (if file deleted)
- **Internal deps**: Cancels timer, removes from tracker

**`get_pending_count() -> int`**
- **Output**: Number of files currently in hold

---

### `src/sophia_learner/watcher/scheduler.py`

#### Classes

**`ProcessingScheduler`**
- **Purpose**: Time-window and delay enforcement
- **Dependencies**: `scheduler.time_window.TimeWindow` (internal), `scheduler.rate_limiter.RateLimiter` (internal)

**`__init__(config: SchedulerConfig)`**
- **Internal deps**: Creates `TimeWindow` and `RateLimiter`

**`can_process_now() -> bool`**
- **Purpose**: Check if current time is within allowed window
- **Output**: Boolean
- **Internal deps**: `self._time_window.is_within_window()`

**`schedule_processing(file_path: Path, priority: int = 5) -> bool`**
- **Purpose**: Either process now or queue for next window
- **Output**: True if queued
- **Internal deps**: Checks window, writes to DB with status='pending'

**`get_next_window_start() -> datetime`**
- **Purpose**: Calculate when next processing window begins

**`wait_for_window()`**
- **Purpose**: Sleep until next window starts (for daemon loop)

**`pause_processing()`** and **`resume_processing()`**
- **Purpose**: Soft pause during user-defined maintenance

---

## 4. Security Layer

### `src/sophia_learner/security/sandbox.py`

#### Classes

**`Sandbox`**
- **Purpose**: Isolate file parsing with resource limits
- **Dependencies**: `resource`, `signal`, `subprocess`

**`__init__(max_cpu_seconds: int = 60, max_memory_mb: int = 512, max_filesize_mb: int = 100)`**
- **Internal deps**: Sets resource limits

**`run_in_sandbox(func: Callable, *args, timeout: int = 30, **kwargs) -> Any`**
- **Purpose**: Execute function with resource limits (uses `multiprocessing` or `resource.setrlimit`)
- **Output**: Function result or raises `SandboxError`
- **Restrictions**: Cannot run if sandbox_mode=False in config
- **External deps**: `multiprocessing.Pool` or `resource` (Linux only)

**`check_file_size(file_path: Path) -> bool`**
- **Output**: True if within limits

**`create_isolated_temp_dir() -> Path`**
- **Purpose**: Create private temp directory for extraction
- **Output**: Path to isolated directory
- **Internal deps**: Uses `tempfile.mkdtemp()` with restricted permissions

**`cleanup_temp_dir(path: Path)`**
- **Purpose**: Securely delete temporary directory

**`set_process_limits()`**
- **Purpose**: Apply resource limits to current process/child
- **External deps**: `resource.RLIMIT_CPU`, `RLIMIT_AS`

---

### `src/sophia_learner/security/validator.py`

#### Functions

**`validate_file_header(file_path: Path, expected_magic_bytes: Dict[str, bytes]) -> bool`**
- **Purpose**: Check magic bytes match extension
- **External deps**: `magic` (python-magic) or manual bytes comparison

**`check_mime_type(file_path: Path, allowed_types: List[str]) -> bool`**
- **Purpose**: Verify MIME type using libmagic
- **External deps**: `magic.from_file()`

**`scan_for_macros(file_path: Path, file_format: str) -> bool`**
- **Purpose**: Detect VBA macros in Office files
- **Output**: True if macros found
- **External deps**: `olefile` for OLE analysis

**`detect_zip_bomb(file_path: Path, ratio_threshold: int = 100) -> bool`**
- **Purpose**: Check if compressed file has unrealistic compression ratio
- **External deps**: `zipfile.ZipFile`

**`validate_filename(filename: str) -> bool`**
- **Purpose**: Reject path traversal chars (`..`, `./`, null bytes)
- **Output**: True if safe

**`check_embedded_objects(file_path: Path) -> List[str]`**
- **Purpose**: List potentially dangerous embedded objects (OLE, scripts)
- **Output**: List of object types found

---

### `src/sophia_learner/security/sanitizer.py`

#### Functions

**`sanitize_text(text: str) -> str`**
- **Purpose**: Remove null bytes, control characters, potential escape sequences
- **Output**: Cleaned string

**`remove_embedded_scripts(xml_content: bytes) -> bytes`**
- **Purpose**: Strip `<script>`, `<object>`, `javascript:` from XML/HTML content

**`strip_vba_macros(ole_file_path: Path) -> Path`**
- **Purpose**: Create copy of Office file with all VBA removed
- **Output**: Path to sanitized copy
- **External deps**: `olefile`, `oletools` (optional)

**`filter_pdf_javascript(pdf_path: Path) -> Path`**
- **Purpose**: Remove JavaScript actions from PDF
- **External deps**: `PyPDF2` or `pdfplumber` with redaction

**`normalize_line_endings(text: str) -> str`**
- **Purpose**: Convert all line endings to `\n`

**`escape_for_json(text: str) -> str`**
- **Purpose**: Ensure string is JSON-safe (quotes, backslashes)

**`truncate_by_bytes(text: str, max_bytes: int) -> str`**
- **Purpose**: Truncate to byte limit without breaking UTF-8

---

### `src/sophia_learner/security/scanner.py`

#### Classes

**`VirusScanner`**
- **Purpose**: Interface to ClamAV or other virus scanners
- **Dependencies**: `subprocess`

**`__init__(scan_command: str = "clamscan --no-summary --infected")`**
- **External deps**: Assumes ClamAV installed

**`scan_file(file_path: Path) -> Tuple[bool, str]`**
- **Output**: `(is_clean, message)`
- **External deps**: Calls `subprocess.run()` with scan command

**`scan_directory(directory: Path) -> Dict[Path, str]`**
- **Output**: Dict of infected files and virus names

**`quarantine_infected(file_path: Path, quarantine_dir: Path) -> Path`**
- **Purpose**: Move infected file to quarantine with timestamp
- **Output**: New quarantine path

**`is_clamav_available() -> bool`**
- **Output**: True if command exists

---

## 5. Parser Layer

### `src/sophia_learner/parser/base_parser.py`

#### Classes

**`BaseParser`** (ABC)
- **Purpose**: Abstract interface for all document parsers
- **Dependencies**: `abc`, `security.sanitizer` (internal)

**`__init__(sandbox: Optional[Sandbox] = None)`**
- **Internal deps**: Stores sandbox reference

**`@abstractmethod extract_text(file_path: Path) -> str`**
- **Input**: Path to file
- **Output**: Extracted plain text
- **Raises**: `ParserError`, `SandboxError`, `SecurityError`
- **Restrictions**: Must be implemented by subclass

**`@abstractmethod get_metadata(file_path: Path) -> Dict`**
- **Output**: Dict with keys like `author`, `creation_date`, `page_count`, `sheet_count`

**`sanitize_output(text: str) -> str`**
- **Purpose**: Common sanitization before returning
- **Internal deps**: `sanitizer.sanitize_text()`

**`validate_input(file_path: Path)`**
- **Purpose**: Check file exists, readable, size within limits
- **Raises**: `FileNotFoundError`, `PermissionError`, `FileSizeError`

**`supports_encryption() -> bool`**
- **Purpose**: Override if parser can handle encrypted files
- **Default**: Returns False
- **Internal deps**: Can raise `EncryptedFileError`

---

### `src/sophia_learner/parser/doc_parser.py`

#### Classes

**`DocParser(BaseParser)`**
- **Purpose**: Parse legacy `.doc` files
- **External deps**: `subprocess` calling `antiword` or `catdoc`

**`extract_text(file_path: Path) -> str`**
- **Implementation**: 
  1. Check if `antiword` available
  2. Run `antiword -w 0 "{file_path}"`
  3. Capture stdout
  4. Fallback to `catdoc` if antiword missing
- **Raises**: `ParserError` if neither tool available

**`get_metadata(file_path: Path) -> Dict`**
- **Implementation**: Parse `antiword -m` output

**`_check_tool_available(tool_name: str) -> bool`**
- **External deps**: `shutil.which()`

---

### `src/sophia_learner/parser/docx_parser.py`

#### Classes

**`DocxParser(BaseParser)`**
- **Purpose**: Parse `.docx` (Office Open XML)
- **External deps**: `docx` (python-docx)

**`extract_text(file_path: Path) -> str`**
- **Implementation**:
  1. Load document with `Document(file_path)`
  2. Extract all paragraphs: `\n`.join(p.text for p in doc.paragraphs)
  3. Extract tables: iterate rows and cells
  4. Extract headers/footers (optional)
- **Restrictions**: Disables external entity resolution internally

**`get_metadata(file_path: Path) -> Dict`**
- **Implementation**: Read `doc.core_properties`

**`_extract_tables(doc) -> str`** (private)
- **Output**: Table content as text

---

### `src/sophia_learner/parser/xls_parser.py`

#### Classes

**`XlsParser(BaseParser)`**
- **Purpose**: Parse legacy `.xls` (binary Excel)
- **External deps**: `xlrd` (book = xlrd.open_workbook(file_path, formatting_info=False))

**`extract_text(file_path: Path) -> str`**
- **Implementation**:
  1. Open workbook with `xlrd.open_workbook(on_demand=True)`
  2. For each sheet: iterate rows, cast each cell to string
  3. Join with tabs/ newlines
- **Restrictions**: `formatting_info=False` for security and speed

**`get_metadata(file_path: Path) -> Dict`**
- **Output**: sheet names, number of rows/cols

**`_cell_to_string(cell) -> str`** (private)
- **Purpose**: Handle different cell types (number, date, text)

---

### `src/sophia_learner/parser/xlsx_parser.py`

#### Classes

**`XlsxParser(BaseParser)`**
- **Purpose**: Parse `.xlsx` (OpenXML Excel)
- **External deps**: `openpyxl` (load_workbook with read_only=True)

**`extract_text(file_path: Path) -> str`**
- **Implementation**:
  1. `load_workbook(file_path, read_only=True, data_only=True)`
  2. For each worksheet: iterate rows, convert values to string
  3. Collect all text
- **Restrictions**: `read_only=True` for memory efficiency

**`get_metadata(file_path: Path) -> Dict`**
- **Implementation**: workbook properties

**`_extract_formulas_as_text(sheet) -> str`** (optional)
- **Purpose**: Extract cell formulas as text (if needed for training)

---

### `src/sophia_learner/parser/pdf_parser.py`

#### Classes

**`PdfParser(BaseParser)`**
- **Purpose**: Extract text from PDF (no OCR)
- **External deps**: `pdfplumber` (preferred) or `PyPDF2`

**`extract_text(file_path: Path) -> str`**
- **Implementation**:
  1. Open with `pdfplumber.open(file_path)`
  2. For each page: `page.extract_text()` or fallback to `PyPDF2`
  3. Join pages with newlines
  4. Limit to max pages (configurable)
- **Restrictions**: No OCR, text-only extraction

**`get_metadata(file_path: Path) -> Dict`**
- **Implementation**: Read PDF info dictionary

**`_extract_pdfplumber(pdf_path) -> str`** (private)
**`_extract_pypdf2(pdf_path) -> str`** (private fallback)

**`supports_encryption() -> bool`**
- **Returns**: False (encrypted PDFs skipped unless password provided)

---

### `src/sophia_learner/parser/parser_registry.py`

#### Global Variables
```python
_PARSERS: Dict[str, Type[BaseParser]] = {}
```

#### Classes

**`ParserRegistry`** (singleton)
- **Purpose**: Map extensions to parser classes

**`register(extension: str, parser_class: Type[BaseParser])`**
- **Purpose**: Add parser to registry
- **Restrictions**: Extension must start with `.`

**`get_parser(extension: str) -> Optional[BaseParser]`**
- **Output**: Instance of parser (cached per extension)
- **Internal deps**: Instantiates parser with sandbox

**`list_supported_extensions() -> List[str]`**

**`get_parser_for_file(file_path: Path) -> Optional[BaseParser]`**
- **Purpose**: Try extension, then fallback to MIME type detection

**`auto_register_builtins()`**
- **Purpose**: Register all implemented parsers on module load

---

## 6. Processor Layer

### `src/sophia_learner/processor/file_processor.py`

#### Classes

**`FileProcessor`**
- **Purpose**: Orchestrate the entire processing pipeline for a single file
- **Dependencies**: `parser.ParserRegistry`, `ai.base_client.AIClient`, `db.FileTracker`, `security.sandbox.Sandbox`, `output.writer.OutputWriter`

**`__init__(config: Settings, db_tracker: FileTracker, version_tracker: VersionTracker, ai_client: AIClient, writer: OutputWriter, sandbox: Sandbox)`**

**`process(file_path: Path, version: Optional[str] = None) -> bool`**
- **Purpose**: Main entry point
- **Output**: True if successful
- **Pipeline steps**:
  1. Validate file (security checks)
  2. Check if already processed (by SHA256)
  3. Detect version from filename (if not provided)
  4. Check for version conflicts
  5. Move to quarantine sandbox
  6. Get appropriate parser
  7. Extract text (within sandbox)
  8. Sanitize extracted content
  9. Send to AI client
  10. Write training data
  11. Update DB with success
  12. Move original to processed archive
- **Internal deps**: `_validate()`, `_check_conflicts()`, `_extract()`, `_ai_process()`, `_write_output()`

**`_validate(file_path: Path) -> Tuple[bool, str]`**
- **Output**: (is_valid, error_message)
- **Internal deps**: Calls `validator.check_mime_type()`, `validator.validate_filename()`

**`_check_conflicts(original_path: Path, version: str) -> bool`**
- **Purpose**: Return True if conflict exists and requires manual resolution
- **Internal deps**: `version_tracker.get_version_chain()`

**`_extract(parser: BaseParser, file_path: Path) -> str`**
- **Internal deps**: `sandbox.run_in_sandbox(parser.extract_text, file_path)`

**`_ai_process(ai_client: AIClient, text: str, metadata: Dict) -> List[Dict]`**
- **Output**: List of training samples

**`_write_output(samples: List[Dict]) -> bool`**
- **Internal deps**: `writer.append()`

---

### `src/sophia_learner/processor/version_detector.py`

#### Global Variables
```python
# Regex patterns for common version schemes
_VERSION_PATTERNS = [
    r'_v(\d+(?:\.\d+)*)',      # _v1, _v2.5
    r'-(\d+(?:\.\d+)*)',        # -1, -2.5.3
    r'\((\d+(?:\.\d+)*)\)',     # (1), (2.0)
    r'\.(\d+)(?=\.\w+$)',       # file.2.pdf → version "2"
    r'_(\d{8})',                # _20240101 (date as version)
]
```

#### Functions

**`detect_version(file_path: Path) -> Optional[str]`**
- **Purpose**: Extract version from stem of filename
- **Input**: Path object
- **Output**: Version string or None
- **Internal deps**: Iterates `_VERSION_PATTERNS`

**`extract_version_number(version_str: str) -> Tuple[int, ...]`**
- **Purpose**: Convert "v2.5.1" to `(2, 5, 1)` for comparison

**`compare_versions(v1: str, v2: str) -> int`**
- **Output**: -1 if v1 < v2, 0 if equal, 1 if v1 > v2

**`get_base_filename(file_path: Path) -> Path`**
- **Purpose**: Remove version suffix from filename
- **Example**: `report_v2.pdf` → `report.pdf`

**`group_by_logical_file(file_paths: List[Path]) -> Dict[str, List[Path]]`**
- **Output**: Map from base name to list of versioned paths

---

### `src/sophia_learner/processor/conflict_resolver.py`

#### Classes

**`ConflictResolver`**
- **Dependencies**: `version_tracker.VersionTracker` (internal), `cli.management_app` (optional)

**`__init__(version_tracker: VersionTracker, mode: str = "manual")`**
- **Internal deps**: Stores mode

**`resolve(conflict_id: int, chosen_version: Optional[str] = None) -> bool`**
- **Purpose**: Resolve conflict (auto or by user choice)
- **Internal deps**: `version_tracker.get_conflict()`, `_auto_resolve()` or `_request_user_input()`

**`_auto_resolve(versions: List[str]) -> str`**
- **Output**: Highest version number (by semantic version)

**`_request_user_input(conflict_id: int, versions: List[str]) -> Optional[str]`**
- **Purpose**: Trigger external management app or CLI prompt
- **Internal deps**: Calls `management_app.prompt_for_resolution()`

**`queue_for_management(conflict_id: int)`**
- **Purpose**: Mark conflict as pending user input
- **Internal deps**: Updates DB

**`get_pending_conflicts() -> List[ConflictRecord]`**

**`notify_user(message: str)`**
- **Purpose**: Send desktop notification if configured
- **External deps**: `subprocess.run(config.notification_command)`

---

### `src/sophia_learner/processor/quarantine.py`

#### Classes

**`Quarantine`**
- **Purpose**: Securely store files before/after processing
- **Dependencies**: `shutil`, `pathlib`, `security.sanitizer`

**`__init__(quarantine_root: Path)`**
- **Structure**:
  - `quarantine_root/incoming/` (raw incoming)
  - `quarantine_root/processing/` (locked for current file)
  - `quarantine_root/processed/` (successful extraction)
  - `quarantine_root/rejected/` (failed security)
  - `quarantine_root/conflicts/` (version conflicts)

**`move_to_quarantine(file_path: Path, stage: str) -> Path`**
- **Purpose**: Move file into quarantine with timestamp
- **Output**: New path in quarantine

**`move_from_quarantine(quarantine_path: Path, destination: Path)`**
- **Purpose**: Restore file (after resolved)

**`mark_processed(quarantine_path: Path)`**
- **Purpose**: Move to `processed/` subfolder

**`mark_rejected(quarantine_path: Path, reason: str)`**
- **Purpose**: Move to `rejected/`, write reason file

**`cleanup_old_files(days: int = 30)`**
- **Purpose**: Delete files older than N days

**`get_quarantine_statistics() -> Dict`**
- **Output**: Counts per stage

---

## 7. AI Layer

### `src/sophia_learner/ai/base_client.py`

#### Classes

**`AIClient`** (ABC)
- **Purpose**: Abstract interface for LLM interaction
- **Dependencies**: `abc`, `typing`

**`@abstractmethod process_text(text: str, metadata: Optional[Dict] = None) -> List[Dict]`**
- **Input**: Extracted text, optional metadata (filename, type)
- **Output**: List of training samples (each a dict matching output_schema)
- **Raises**: `AIConnectionError`, `AITimeoutError`, `AIResponseError`

**`@abstractmethod health_check() -> bool`**
- **Output**: True if AI backend is reachable and responsive

**`@abstractmethod get_model_info() -> Dict`**
- **Output**: Model name, version, context length

**`format_prompt(content: str, template: str) -> str`**
- **Purpose**: Render prompt template with content
- **Internal deps**: Uses `str.format()` or Jinja2

**`validate_response(response: Dict, schema: Dict) -> bool`**
- **Purpose**: Ensure output conforms to expected schema

**`_parse_json_response(raw_response: str) -> Dict`**
- **Purpose**: Safely extract JSON from LLM response (may contain markdown)

---

### `src/sophia_learner/ai/ollama_client.py`

#### Classes

**`OllamaClient(AIClient)`**
- **Purpose**: Interact with local Ollama instance
- **External deps**: `httpx` (async) or `requests`

**`__init__(base_url: str, model: str, timeout: int, max_tokens: int, temperature: float)`**

**`process_text(text: str, metadata: Optional[Dict] = None) -> List[Dict]`**
- **Implementation**:
  1. Format prompt using `self.format_prompt()`
  2. POST to `{base_url}/api/generate`
  3. Payload: `{"model": model, "prompt": prompt, "stream": False, "options": {"num_predict": max_tokens, "temperature": temperature}}`
  4. Parse response JSON
  5. Validate and return

**`health_check() -> bool`**
- **Implementation**: GET `{base_url}/api/tags`, check response

**`_call_api(prompt: str) -> str`**
- **Purpose**: Raw API call with retries
- **Internal deps**: `utils.retry.retry()`

---

### `src/sophia_learner/ai/transformers_client.py`

#### Classes

**`TransformersClient(AIClient)`**
- **Purpose**: Load Hugging Face model directly
- **External deps**: `transformers`, `torch`, `accelerate`

**`__init__(model_name: str, device: str = "cuda", load_in_8bit: bool = False)`**
- **Implementation**: Load model and tokenizer

**`process_text(text: str, metadata: Optional[Dict] = None) -> List[Dict]`**
- **Implementation**:
  1. Format prompt
  2. Tokenize input
  3. `model.generate()` with appropriate parameters
  4. Decode output
  5. Parse JSON

**`health_check() -> bool`**
- **Output**: True if model loaded and device available

**`_free_memory()`**
- **Purpose**: Clear GPU cache when idle

**Note**: This client is memory-intensive; consider using with `sandbox` for isolation.

---

### `src/sophia_learner/ai/prompt_templates.py`

#### Classes

**`PromptTemplate`**
- **Purpose**: Manage and render prompt templates
- **Dependencies**: `jinja2` (optional) or simple `str.format`

**`__init__(template_path: Optional[Path] = None)`**
- **Internal deps**: Loads from file or uses default

**`render(content: str, context: Optional[Dict] = None) -> str`**
- **Input**: Content to insert, additional variables
- **Output**: Final prompt string

**`get_default_template() -> str`**
- **Output**: Built-in prompt for generating instruction-output pairs

**`validate_template(template: str) -> bool`**
- **Purpose**: Check for syntax errors and safe placeholders

**Built-in templates**:
- `DEFAULT` → Instruction-output generation
- `QA_PAIR` → Question-answer from document
- `SUMMARY` → Summarization task
- `CLASSIFICATION` → Label extraction

---

### `src/sophia_learner/ai/training_formatter.py`

#### Classes

**`TrainingFormatter`**
- **Purpose**: Format AI output to standard training data
- **Dependencies**: `json`

**`__init__(output_schema: Dict)`**
- **Internal deps**: Stores expected fields

**`to_jsonl(samples: List[Dict], file_handle: TextIO)`**
- **Purpose**: Append each sample as JSON line

**`to_json(samples: List[Dict], file_handle: TextIO, indent: int = 2)`**
- **Purpose**: Write as JSON array

**`validate_sample(sample: Dict) -> bool`**
- **Purpose**: Check required fields exist, types correct

**`add_metadata(sample: Dict, source_file: Path, timestamp: datetime) -> Dict`**
- **Purpose**: Enrich sample with provenance

**`deduplicate_samples(samples: List[Dict]) -> List[Dict]`**
- **Purpose**: Remove identical samples (hash-based)

---

## 8. Output Layer

### `src/sophia_learner/output/writer.py`

#### Classes

**`OutputWriter`**
- **Purpose**: Thread-safe, atomic writing to training data files
- **Dependencies**: `threading.Lock`, `output.rotator.Rotator` (internal)

**`__init__(config: OutputConfig, formatter: TrainingFormatter)`**
- **Internal deps**: Creates rotator, opens file handle

**`append(sample: Dict) -> bool`**
- **Purpose**: Write single sample (acquires lock)
- **Internal deps**: `_write()`, `rotator.check_rotate()`

**`append_batch(samples: List[Dict]) -> int`**
- **Output**: Number written successfully

**`_write(sample: Dict)`**
- **Purpose**: Raw write (assumes lock held)

**`flush()`**
- **Purpose**: Flush buffers to disk

**`close()`**
- **Purpose**: Close file handle, run final rotation

**`get_current_output_path() -> Path`**
- **Output**: Current active JSONL file

---

### `src/sophia_learner/output/rotator.py`

#### Classes

**`Rotator`**
- **Purpose**: Manage file size and date-based rotation
- **Dependencies**: `pathlib`, `gzip` (for compression)

**`__init__(output_dir: Path, max_size_mb: int, rotate_daily: bool, compress: bool)`**

**`check_rotate(current_path: Path, current_size_mb: float) -> Path`**
- **Purpose**: Create new file if rotation criteria met
- **Output**: Path to current output file

**`_rotate_by_size(current_path: Path) -> Path`**
- **Implementation**: Rename to `training_data_YYYYMMDD_HHMMSS.jsonl`

**`_rotate_by_date(current_path: Path) -> Path`**
- **Implementation**: Check if date changed

**`compress_file(file_path: Path) -> Path`**
- **Output**: Path to `.gz` archive
- **External deps**: `gzip.open()`

**`get_archive_list() -> List[Path]`**
- **Output**: All rotated/archived files

**`cleanup_old_archives(days_to_keep: int = 90)`**

---

### `src/sophia_learner/output/metrics.py`

#### Classes

**`MetricsCollector`**
- **Purpose**: Collect and report training data metrics
- **Dependencies**: `db.Database` (internal)

**`__init__(db: Database)`**

**`log_sample(sample: Dict, processing_time_ms: int, token_count: int)`**
- **Internal deps**: `_db.execute()` insert into metrics table

**`get_daily_stats(date: Optional[date] = None) -> Dict`**

**`generate_report(period: str = "week") -> str`**
- **Output**: Human-readable report (Markdown)

**`increment_counter(metric_name: str)`**
- **Purpose**: Simple increment (files_processed, ai_calls, etc.)

**`record_timing(operation: str, duration_ms: int)`**

---

## 9. Scheduler Layer

### `src/sophia_learner/scheduler/time_window.py`

#### Classes

**`TimeWindow`**
- **Purpose**: Daily time window logic (e.g., 17:00 to 07:00 next day)
- **Dependencies**: `datetime`, `pytz` (optional)

**`__init__(start_str: str, end_str: str, timezone_str: str = "UTC")`**
- **Input**: "17:00", "07:00", "Europe/Berlin"

**`is_within_window(dt: Optional[datetime] = None) -> bool`**
- **Input**: Current time (default = now)
- **Output**: True if within window

**`get_next_window_start(dt: Optional[datetime] = None) -> datetime`**
- **Output**: Next datetime when window begins

**`seconds_until_window(dt: Optional[datetime] = None) -> float`**
- **Output**: Seconds to wait (0 if currently in window)

**`get_window_duration_seconds() -> int`**

**`_parse_time(time_str: str) -> time`**
- **Internal**: "17:00" → `time(17, 0)`

---

### `src/sophia_learner/scheduler/rate_limiter.py`

#### Classes

**`RateLimiter`**
- **Purpose**: Enforce delay between file processing
- **Dependencies**: `time`, `threading.Lock`

**`__init__(delay_seconds: int)`**

**`wait_if_needed()`**
- **Purpose**: Sleep if last processing was less than delay_seconds ago
- **Internal deps**: `self._last_process_time`, `time.sleep()`

**`record_processing()`**
- **Purpose**: Update last process timestamp

**`set_delay(delay_seconds: int)`**
- **Purpose**: Dynamic delay adjustment

**`reset()`**
- **Purpose**: Clear last process time (for testing)

**`get_remaining_cooldown() -> float`**
- **Output**: Seconds until next allowed processing

---

### `src/sophia_learner/scheduler/backfill.py`

#### Classes

**`BackfillProcessor`**
- **Purpose**: Discover and queue existing files not yet processed
- **Dependencies**: `db.FileTracker`, `processor.version_detector`

**`__init__(file_tracker: FileTracker, version_detector: VersionDetector)`**

**`scan_folders(watch_folders: List[Path], extensions: List[str]) -> List[Path]`**
- **Output**: All files matching extensions

**`filter_unprocessed(files: List[Path]) -> List[Path]`**
- **Purpose**: Remove files already in DB with status='processed'
- **Internal deps**: `file_tracker.get_file_by_path()`

**`enqueue_for_processing(file_paths: List[Path], priority: int = 3)`**
- **Purpose**: Add to DB with status='pending'

**`run_backfill(watch_folders: List[Path], extensions: List[str], max_files: int = 1000) -> int`**
- **Output**: Number of files queued

**`should_backfill_on_startup(config: Settings) -> bool`**
- **Output**: Based on config setting

---

### `src/sophia_learner/scheduler/cron_manager.py`

#### Classes

**`CronManager`**
- **Purpose**: Optional integration with system cron (for external scheduling)
- **Dependencies**: `subprocess`, `crontab` (python-crontab optional)

**`sync_with_cron(command: str, schedule: str)`**
- **Purpose**: Install/update crontab entry
- **Input**: Schedule like "0 17 * * *"

**`remove_cron_job(command: str)`**

**`get_current_cron_jobs() -> List[str]`**

**`is_cron_available() -> bool`**
- **Output**: Check if crontab command exists

**Note**: This is optional; main scheduler runs in-process.

---

## 10. CLI & Management

### `src/sophia_learner/cli/commands.py`

#### Functions (using `click` or `argparse`)

**`main()`** (entry point)
- **Purpose**: Parse CLI arguments and dispatch

**`start(args)`**
- **Purpose**: Start daemon/service
- **Internal deps**: Calls `main.run_daemon()`

**`stop(args)`**
- **Purpose**: Gracefully stop service (via PID file or signal)

**`status(args)`**
- **Purpose**: Print current status (watching folders, queue size)
- **Internal deps**: `status_reporter.print_status()`

**`conflicts(args)`**
- **Purpose**: List and resolve conflicts
- **Internal deps**: `management_app.show_conflicts()`

**`backfill(args)`**
- **Purpose**: Manually trigger backfill scan

**`config(args)`**
- **Purpose**: Show or validate configuration

**`metrics(args)`**
- **Purpose**: Display training metrics

**`quarantine(args)`**
- **Purpose**: List/manage quarantine

---

### `src/sophia_learner/cli/management_app.py`

#### Classes

**`ConflictManagementApp`**
- **Purpose**: TUI/CLI for user to resolve version conflicts
- **Dependencies**: `rich` or `prompt_toolkit` (optional), `db.VersionTracker`

**`__init__(version_tracker: VersionTracker)`**

**`show_conflicts() -> bool`**
- **Purpose**: Display pending conflicts and prompt user
- **Output**: True if any resolved

**`_display_conflict(conflict: ConflictRecord, versions: List[FileRecord]) -> str`**
- **Output**: Chosen version string

**`_preview_file(file_path: Path, max_lines: int = 10)`**
- **Purpose**: Show first few lines to help decision

**`resolve_all_auto()`**
- **Purpose**: Auto-resolve all pending (keep latest)

**`export_conflict_list(output_path: Path)`**
- **Purpose**: Save conflict list to CSV for external processing

---

### `src/sophia_learner/cli/status_reporter.py`

#### Functions

**`print_status(db: Database, watcher: DirectoryWatcher, scheduler: ProcessingScheduler)`**
- **Purpose**: Pretty-print system status
- **Output**: Tables with counts, next window, queue sizes

**`print_queue(file_tracker: FileTracker, limit: int = 20)`**
- **Purpose**: Show pending files

**`print_metrics(metrics: MetricsCollector, days: int = 7)`**
- **Purpose**: Show training progress

**`print_version_conflicts(version_tracker: VersionTracker)`**

**`print_watcher_status(watcher: DirectoryWatcher)`**
- **Purpose**: Show which folders are being watched

**`generate_html_report(db: Database, output_path: Path)`**
- **Purpose**: Export dashboard

---

## 11. Utilities

### `src/sophia_learner/utils/logger.py`

#### Global Variables
```python
_LOGGERS: Dict[str, logging.Logger] = {}
_SECURITY_LOGGER: Optional[logging.Logger] = None
```

#### Functions

**`setup_logging(config: LoggingConfig) -> None`**
- **Purpose**: Configure rotating file handlers, console handler
- **External deps**: `logging`, `logging.handlers.RotatingFileHandler`

**`get_logger(name: str) -> logging.Logger`**
- **Output**: Logger instance with consistent formatting

**`get_security_logger() -> logging.Logger`**
- **Purpose**: Dedicated logger for security events (separate file)

**`log_security_event(event_type: str, file_path: Path, details: Dict)`**
- **Purpose**: Structured security logging (JSON format)

**`set_log_level(level: str)`**
- **Purpose**: Dynamic log level adjustment

---

### `src/sophia_learner/utils/file_utils.py`

#### Functions

**`safe_copy(src: Path, dst: Path, preserve_metadata: bool = False)`**
- **Purpose**: Copy with error handling and permissions

**`atomic_write(file_path: Path, content: Union[str, bytes])`**
- **Purpose**: Write to temp file, then rename (atomic)

**`get_file_size_safe(file_path: Path) -> int`**
- **Purpose**: Return size, handle permission errors

**`ensure_directory(path: Path, mode: int = 0o750)`**
- **Purpose**: Create directory with safe permissions

**`secure_delete(file_path: Path, passes: int = 1)`**
- **Purpose**: Overwrite before delete (for sensitive files)

**`is_path_safe(base_dir: Path, target_path: Path) -> bool`**
- **Purpose**: Prevent path traversal attacks

**`get_unique_filename(directory: Path, prefix: str = "", suffix: str = "") -> Path`**
- **Purpose**: Generate non-conflicting filename

**`wait_for_file_stable(file_path: Path, check_interval: float = 0.5, max_wait_seconds: int = 30)`**
- **Purpose**: Wait for file size to stop changing (detect complete write)

---

### `src/sophia_learner/utils/hash_utils.py`

#### Functions

**`compute_sha256(file_path: Path, chunk_size: int = 8192) -> str`**
- **Output**: Hex digest
- **Internal deps**: `hashlib.sha256()`

**`compute_hash_chunked(file_path: Path, max_bytes: int = None) -> str`**
- **Purpose**: Hash only first N bytes (for quick dedup)

**`verify_hash(file_path: Path, expected_hash: str) -> bool`**

**`hash_string(text: str) -> str`**
- **Purpose**: SHA256 of UTF-8 string

**`hash_dict(data: Dict) -> str`**
- **Purpose**: Stable hash of JSON-serializable dict

---

### `src/sophia_learner/utils/time_utils.py`

#### Functions

**`wait_until(target_time: datetime, poll_interval: float = 1.0)`**
- **Purpose**: Sleep until specific datetime

**`parse_time_window(window_str: str) -> Tuple[time, time]`**
- **Input**: "17:00-07:00" → start, end

**`human_duration(seconds: int) -> str`**
- **Output**: "2 days, 3 hours, 15 minutes"

**`to_iso8601(dt: datetime) -> str`**

**`from_iso8601(iso_str: str) -> datetime`**

**`get_timezone_aware_now(timezone_str: str) -> datetime`**

**`format_timestamp(dt: datetime, format: str = "%Y-%m-%d %H:%M:%S")`**

---

### `src/sophia_learner/utils/retry.py`

#### Functions

**`retry(max_attempts: int = 3, delay: float = 1.0, backoff: float = 2.0, exceptions: Tuple = (Exception,))`**
- **Purpose**: Decorator for retry logic
- **Usage**:
  ```python
  @retry(max_attempts=3, delay=2, exceptions=(ConnectionError, TimeoutError))
  def call_api():
      ...
  ```

**`retry_async(same as above)`**
- **Purpose**: Async version for async functions

**`RetryStrategy`** (class)
- **Methods**: `linear`, `exponential`, `fibonacci`

**`is_retryable_error(error: Exception, retryable_types: Tuple) -> bool`**

---

## External Dependencies Summary

| Category | Libraries | Installation |
|----------|-----------|--------------|
| **Core** | watchdog, PyYAML, pydantic | `pip install watchdog pyyaml pydantic` |
| **Parsing** | python-docx, openpyxl, xlrd, pdfplumber, PyPDF2, antiword (system) | `pip install python-docx openpyxl xlrd pdfplumber pypdf2`<br>`sudo apt install antiword catdoc` |
| **AI** | ollama (separate), httpx, transformers, torch, accelerate | `pip install httpx transformers torch accelerate`<br>(Install Ollama separately) |
| **Security** | python-magic, olefile, oletools (optional) | `pip install python-magic olefile`<br>`pip install oletools` (optional) |
| **CLI** | click, rich, prompt_toolkit | `pip install click rich prompt-toolkit` |
| **Templating** | jinja2 (optional) | `pip install jinja2` |
| **Timezone** | pytz | `pip install pytz` |
| **DB** | sqlite3 (stdlib) | Built-in |
| **Testing** | pytest, pytest-cov, pytest-mock | `pip install pytest pytest-cov pytest-mock` |

---

## Internal Dependency Graph (Simplified)

```
Level 0 (No internal deps):
├── utils/* (logger, hash_utils, time_utils, retry)
├── config/schema.py
├── db/database.py
└── security/sanitizer.py (only utils)

Level 1 (depends on Level 0):
├── config/settings.py (depends on schema)
├── db/models.py (depends on database)
├── security/validator.py (depends on utils)
├── security/sandbox.py (depends on utils)
├── security/scanner.py (depends on utils)
└── scheduler/time_window.py (depends on utils)

Level 2 (depends on Level 0-1):
├── db/file_tracker.py (depends on database, models)
├── db/version_tracker.py (depends on database, models)
├── parser/base_parser.py (depends on security/sanitizer, utils)
├── ai/base_client.py (depends on utils/retry)
├── output/formatter.py (depends on utils)
└── scheduler/rate_limiter.py (no deps beyond stdlib)

Level 3 (depends on Level 2):
├── parser/*_parser.py (depends on base_parser, security/sandbox)
├── ai/ollama_client.py (depends on base_client, utils/retry)
├── ai/transformers_client.py (depends on base_client)
├── ai/prompt_templates.py (no heavy deps)
├── output/writer.py (depends on formatter, rotator)
├── output/rotator.py (depends on utils/file_utils)
├── scheduler/backfill.py (depends on db/file_tracker, version_detector)
└── processor/version_detector.py (stdlib only)

Level 4 (Core orchestration):
├── watcher/debouncer.py (depends on scheduler, db)
├── watcher/event_handler.py (depends on debouncer)
├── watcher/directory_watcher.py (depends on event_handler)
├── processor/file_processor.py (depends on: parser registry, ai client, db trackers, output writer, security)
├── processor/conflict_resolver.py (depends on version_tracker, cli/management_app)
├── processor/quarantine.py (depends on security/sanitizer, utils)

Level 5 (Integration):
├── main.py (depends on all above)
├── cli/commands.py (depends on main, status_reporter, management_app)
└── scheduler/cron_manager.py (optional, external)

Level 6 (Standalone):
└── cli/management_app.py (depends on db, processor)
```

---

## Next Step: Prioritization for Development

Based on **minimal internal dependencies first**, here is the recommended order:

### **Phase 1: Foundation (No dependencies)**
1. `utils/logger.py`
2. `utils/hash_utils.py`
3. `utils/time_utils.py`
4. `utils/retry.py`
5. `utils/file_utils.py`
6. `config/schema.py`

### **Phase 2: Security & DB Core**
7. `security/sanitizer.py`
8. `db/database.py`
9. `db/models.py`
10. `security/validator.py`
11. `security/sandbox.py`

### **Phase 3: Tracking & Scheduling Basics**
12. `db/file_tracker.py`
13. `db/version_tracker.py`
14. `scheduler/time_window.py`
15. `scheduler/rate_limiter.py`

### **Phase 4: Parsers (external libs, but isolated)**
16. `parser/base_parser.py`
17. `parser/doc_parser.py`
18. `parser/docx_parser.py`
19. `parser/xls_parser.py`
20. `parser/xlsx_parser.py`
21. `parser/pdf_parser.py`
22. `parser/parser_registry.py`

### **Phase 5: AI Layer**
23. `ai/base_client.py`
24. `ai/prompt_templates.py`
25. `ai/ollama_client.py`
26. `ai/transformers_client.py`
27. `ai/training_formatter.py`

### **Phase 6: Output Management**
28. `output/rotator.py`
29. `output/writer.py`
30. `output/metrics.py`

### **Phase 7: Processing Core**
31. `processor/version_detector.py`
32. `processor/quarantine.py`
33. `scheduler/backfill.py`
34. `processor/conflict_resolver.py`
35. `processor/file_processor.py`

### **Phase 8: Watcher & Scheduler Integration**
36. `watcher/debouncer.py`
37. `watcher/event_handler.py`
38. `watcher/directory_watcher.py`
39. `scheduler/cron_manager.py`

### **Phase 9: CLI & Management**
40. `cli/status_reporter.py`
41. `cli/management_app.py`
42. `cli/commands.py`
43. `main.py`

### **Phase 10: Configuration & Testing**
44. `config/settings.py`
45. `tests/*` (all test files)
46. `scripts/*` (systemd, init scripts)

end of document.
