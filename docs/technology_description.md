# Technology Description: Sophia Learner

## 1. System Architecture Overview

Sophia Learner is a modular Python-based framework that transforms documents into AI training data through a secure, multi-stage pipeline.

### High-Level Process Flow

```
Raw Documents → Security Validation → Content Extraction → AI Processing → Training Data
     ↓                ↓                    ↓                  ↓                ↓
 Watched          Quarantine           Sandboxed          Local LLM        JSONL Files
 Folders          & Scanning           Parsers            (Ollama)         with Metadata
```

### Detailed Processing Pipeline

#### Stage 1: File Discovery & Hold
- **Watchdog** library monitors directories using Linux inotify
- When a file appears, it enters a **24-hour debounce** period
- During hold, file modifications reset the timer
- After hold expires, file moves to processing queue

#### Stage 2: Security & Validation
- MIME type verification (rejects renamed malwares)
- Macro/script detection in Office files
- Optional ClamAV virus scan
- Size and resource limit checks
- Suspicious files moved to quarantine (never parsed)

#### Stage 3: Content Extraction (Sandboxed)
- File type-specific parser selected from registry
- Parsing occurs in resource-limited sandbox:
  - Max 60 seconds CPU time
  - Max 512MB RAM
  - Max 100MB file size
- Extraction results sanitized:
  - Null bytes removed
  - Control characters stripped
  - Line endings normalized
- Office macros stripped before extraction

#### Stage 4: Version Detection & Conflict Resolution
- Filename parsed for version patterns (`_v2`, `-1.5`, `(3)`)
- Version chain grouped by logical file name
- If multiple versions exist, system either:
  - Automatically keeps highest version (configurable)
  - Queues for manual user resolution via management app

#### Stage 5: AI Processing
- Extracted text sent to local AI model (Ollama or Transformers)
- Prompt template applied (customizable per document type)
- AI generates training samples (instruction-output pairs, QA, summaries)
- Response validated against output schema
- Malformed responses retried (max 3 attempts)

#### Stage 6: Output Generation
- Training samples written to JSONL files
- Automatic rotation at 500MB or daily
- Optional compression (gzip) for archives
- Metrics collected: tokens, processing time, sample counts

#### Stage 7: State Persistence
- SQLite database tracks every file's journey
- Records: file metadata, processing status, version conflicts, metrics
- Enables resume after restart and audit trails

## 2. Technology Stack

### Core Technologies

| Component | Technology | Version | Purpose |
|-----------|------------|---------|---------|
| Language | Python | 3.10+ | Primary development language |
| File Watching | Watchdog | 3.0+ | OS-level filesystem events |
| Database | SQLite | 3.35+ | State and metadata storage |
| Configuration | YAML + Pydantic | 6.0+ / 2.0+ | Type-safe configuration |
| Logging | Python logging + RotatingFileHandler | stdlib | Structured logs with rotation |

### Document Parsing Libraries

| Format | Library | Version | Security Notes |
|--------|---------|---------|----------------|
| .docx | python-docx | 0.8.11 | read-only, no external entities |
| .doc | antiword/catdoc | system tool | subprocess with sandbox |
| .xlsx | openpyxl | 3.1.0 | read-only mode, data_only=True |
| .xls | xlrd | 2.0.1 | formatting_info=False (disables BIFF) |
|  |  |  |  |
| .xls | xlrd | 2.0.1 | formatting_info=False (disables BIFF) |
| .xls | xlrd | 2.0.1 | formatting_info=False |
| .pdf | pdfplumber | 0.10.0 | page-by-page streaming |
| .pdf (fallback) | PyPDF2 | 3.0.0 | no JavaScript execution |

### AI Integration

| Backend | Method | Requirements | Use Case |
|---------|--------|--------------|----------|
| Ollama | REST API | Ollama server + model (llama3, mistral) | Recommended, easiest setup |
| Transformers | Direct load | 8GB+ RAM, GPU optional | Custom fine-tuned models |

### Security Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| Sandboxing | Python `resource` + `multiprocessing` | CPU/memory limits |
| MIME Validation | `python-magic` (libmagic) | File type verification |
| Macro Detection | `olefile` + pattern matching | VBA/ActiveX detection |
| Virus Scanning | ClamAV (optional) | Malware detection |
| Path Sanitization | Custom regex | Path traversal prevention |
| XML Security | Disable external entities | XXE attack prevention |

## 3. Prerequisites

### Hardware Requirements

#### Minimum Configuration
- **CPU**: 2 cores (x86_64 or ARM64)
- **RAM**: 8GB (4GB for system + 4GB for AI model)
- **Storage**: 10GB free + document storage space
- **Network**: Localhost only (no external internet required after setup)

#### Recommended Configuration
- **CPU**: 4+ cores
- **RAM**: 16GB (for 7B parameter models)
- **Storage**: 50GB+ SSD
- **GPU**: NVIDIA GPU with 6GB+ VRAM (optional, for faster AI)

#### Performance Estimates
- Document parsing: ~0.5-2 seconds per page (PDF)
- AI processing: ~5-30 seconds per document (depends on model)
- Processing rate: ~100-500 documents per hour (with 15s delay)

### Software Stack

#### Operating System
- **Linux** (tested on):
  - Ubuntu 20.04 / 22.04 / 24.04
  - Debian 11 / 12
  - Rocky Linux 8 / 9
  - Fedora 38+
- **Required kernel**: 2.6.22+ (for inotify)

#### System Dependencies

```bash
# Ubuntu/Debian
sudo apt update
sudo apt install -y python3.10 python3-pip python3-venv
sudo apt install -y antiword catdoc        # Legacy .doc support
sudo apt install -y libmagic1              # MIME detection
sudo apt install -y clamav clamav-daemon   # Optional virus scanning

# RHEL/Rocky/Fedora
sudo dnf install -y python3.10 python3-pip
sudo dnf install -y antiword catdoc
sudo dnf install -y file-libs              # libmagic
sudo dnf install -y clamav clamav-update   # Optional
```

#### Python Environment

```bash
# Create virtual environment
python3.10 -m venv sophia_env
source sophia_env/bin/activate

# Core dependencies
pip install --upgrade pip
pip install watchdog pyyaml pydantic
pip install python-docx openpyxl xlrd pdfplumber
pip install httpx                       # For Ollama client
```

#### Optional AI Backend Installation

**Option A: Ollama (Recommended)**
```bash
# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Pull a model (first time only)
ollama pull llama3.2:3b   # 3B parameter, ~2GB RAM
# or
ollama pull mistral:7b    # 7B parameter, ~6GB RAM

# Start Ollama service
sudo systemctl enable ollama
sudo systemctl start ollama
```

**Option B: Hugging Face Transformers**
```bash
pip install transformers torch accelerate

# For GPU support (optional)
pip install torch --index-url https://download.pytorch.org/whl/cu118
```

### Configuration Prerequisites

#### File System Layout

Create required directories before first run:

```bash
mkdir -p /opt/sophia_learner/{data,logs,certs,tmp}
mkdir -p /opt/sophia_learner/data/{quarantine,AI-Training}
mkdir -p /opt/sophia_learner/data/quarantine/{incoming,processing,processed,rejected,conflicts}

# Set secure permissions
chmod 750 /opt/sophia_learner/data/quarantine
chmod 750 /opt/sophia_learner/logs
```

#### Watched Folders

Create or designate folders to monitor:

```bash
mkdir -p /var/sophia/incoming
chmod 755 /var/sophia/incoming
chown sophia_user:sophia_group /var/sophia/incoming
```

> **Note**: Sophia Learner never modifies original files; it copies/quarantines them.

## 4. Security Implementation Details

### Defense in Depth Layers

```
Layer 1: Input Validation
├── Filename sanitization (reject ../, null bytes)
├── Extension whitelist
├── Magic byte verification (prevents extension spoofing)
└── Size limits (reject ZIP bombs)

Layer 2: Quarantine & Scanning
├── Files moved to isolated quarantine directory
├── Optional ClamAV scan before any parsing
├── Macro detection (Office documents)
└── Suspicious files rejected (never parsed)

Layer 3: Sandboxed Parsing
├── Process isolated with resource limits
├── CPU time limit (60 seconds)
├── Memory limit (512MB)
├── No network access (by process isolation)
└── Timeout enforced (30 seconds)

Layer 4: Content Sanitization
├── Null bytes removed
├── Control characters stripped
├── XML external entities disabled
├── VBA macros stripped (not just disabled)
└── PDF JavaScript removed

Layer 5: AI Prompt Safety
├── Input content escaped
├── Prompt delimiters prevent injection
├── Output validated against schema
└── Max token limits enforced

Layer 6: Output Protection
├── JSON encoding escapes dangerous characters
├── File writes with atomic operations
├── No executable bits on output files
└── Separate output directory from source
```

### Quarantine System

Files follow this lifecycle through quarantine:

1. **Incoming**: Original file copied upon first detection
2. **Processing**: Locked file during active processing
3. **Processed**: Successfully transformed, kept for 30 days
4. **Rejected**: Failed security checks, kept for audit
5. **Conflicts**: Version conflicts pending user resolution

Quarantine directory has 750 permissions (owner/group only).

### Data Privacy Guarantees

- **No external API calls** – All AI runs locally
- **No telemetry** – Framework phones home to nothing
- **Encryption at rest** – Use LUKS/ecryptfs on data directory (optional)
- **Secure deletion** – Optional overwrite before delete
- **Audit logs** – Complete chain of custody for every file

## 5. Operation Modes

### Daemon Mode (Production)
```bash
sophia-learner start          # Runs as background process
sophia-learner stop           # Graceful shutdown
sophia-learner status         # Check health
```

### Interactive Mode (Management)
```bash
sophia-learner conflicts      # Resolve version conflicts
sophia-learner backfill       # Process existing files
sophia-learner metrics        # View training statistics
```

### Systemd Service (Auto-start)
```bash
sudo systemctl enable sophia-learner
sudo systemctl start sophia-learner
```

## 6. Configuration Reference

### Essential Settings

| Setting | Example | Description |
|---------|---------|-------------|
| `watcher.watch_folders` | `["/var/incoming"]` | Directories to monitor |
| `watcher.hold_hours` | `24` | Hours to wait before processing |
| `scheduler.processing_window` | `start: "17:00", end: "07:00"` | Daily processing window |
| `scheduler.delay_between_files_seconds` | `900` | 15 minutes between files |
| `security.max_file_size_mb` | `100` | Reject larger files |
| `ai.backend` | `ollama` or `transformers` | AI engine |
| `ai.ollama.model` | `llama3.2:3b` | Model to use |

### Security Tuning

For **high-security environments**, enable:
```yaml
security:
  sandbox_mode: true
  enable_virus_scan: true
  strip_macros: true
  max_file_size_mb: 10          # Stricter limit
  allowed_mime_types:           # Very specific whitelist
    - "application/pdf"
    - "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
```

For **performance environments**, disable:
```yaml
security:
  enable_virus_scan: false      # Skip ClamAV
  sandbox_mode: false           # Slightly faster (less safe)
```

## 7. Troubleshooting Prerequisites

### Common Issues & Requirements

| Issue | Check | Solution |
|-------|-------|----------|
| Python version too old | `python3 --version` | Install Python 3.10+ from deadsnakes PPA |
| inotify limit reached | `cat /proc/sys/fs/inotify/max_user_watches` | Increase: `echo 524288 | sudo tee /proc/sys/fs/inotify/max_user_watches` |
| antiword not found | `which antiword` | `sudo apt install antiword` |
| Ollama connection refused | `curl http://localhost:11434/api/tags` | Start Ollama: `systemctl start ollama` |
| Permission denied on watched folder | `ls -la /path/to/folder` | Run sophia-learner as folder owner |
| DB locked | Check for stale `.lock` file | Restart service, remove lock if process dead |

### Log Locations

- Main log: `/var/log/sophia_learner/sophia_learner.log`
- Security events: `/var/log/sophia_learner/security.log`
- Processing errors: `/var/log/sophia_learner/errors.log`
- Database: `/opt/sophia_learner/data/sophia.db`

## 8. Performance Optimization Prerequisites

### For High Volume (1000+ files/day)

- **Storage**: Use SSD, not HDD (SQLite benefits greatly)
- **RAM**: 32GB+ if running 13B+ parameter models
- **CPU**: 8+ cores for parallel parsing
- **Database**: Enable WAL mode: `PRAGMA journal_mode=WAL;`
- **Batch size**: Set `max_files_per_batch: 50`

### For Low Resource (Raspberry Pi / VM)

- **Model**: Use tiny models (Phi-2, TinyLlama)
- **Parsers**: Disable PDF OCR fallbacks
- **Sandbox**: Reduce memory limit to 256MB
- **Delay**: Increase to 60 seconds between files
- **Database**: Disable backup during processing

## 9. Network Requirements

Sophia Learner is designed for **air-gapped or isolated networks**:

**No mandatory external connections** after initial setup:
- AI models downloaded once (Ollama pulls, or pre-loaded)
- No phoning home, no telemetry
- All processing occurs on localhost

**Optional external dependencies** (disable in config):
- ClamAV signature updates (can be offline)
- VirusTotal integration (disabled by default)

## 10. Compliance & Auditing

Sophia Learner provides features for regulatory compliance (GDPR, HIPAA, etc.):

- **Complete audit trail**: SQLite logs every file action
- **Data retention policies**: Configurable quarantine auto-cleanup
- **Secure deletion**: Optional file overwrite
- **Separation of duties**: Management app requires separate auth (planned)
- **Chain of custody**: Every processing step logged with timestamp

For audit queries:
```sql
-- Show all files processed in last 24 hours
SELECT path, status, created_at FROM files 
WHERE created_at > datetime('now', '-1 day');

-- Show security events for a specific file
SELECT * FROM processing_log 
WHERE file_id = (SELECT id FROM files WHERE path = '/path/to/file')
AND stage = 'security';
