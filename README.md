# Sophia Learner
Let your machine read and learn your data.

**Intelligent Document Processing Pipeline for AI Training Data Generation**

Sophia Learner is a secure, automated framework that watches designated folders for documents, extracts their content, processes them through local AI models, and generates structured training data for machine learning.

## Overview

Sophia Learner solves the challenge of converting raw documents (PDFs, Word files, Excel spreadsheets) into high-quality AI training data. It operates entirely locally on Linux systems, ensuring data privacy and security while providing enterprise-grade features:

- **Delayed hold policy** – Ensures users have finished editing files before processing (Configurable, e.g., 24h)
- **Version awareness** – Detects and manages multiple file versions with conflict resolution
- **Scheduled processing** – Runs during off-hours (configurable, e.g., 5 PM to 7 AM)
- **Security-first design** – Sandboxed parsing, macro stripping, virus scanning integration
- **Local AI integration** – Works with Ollama, Hugging Face models, or custom endpoints
- **SQLite state management** – Tracks every file with complete audit trail

## Documentation

- [Technology Description](docs/technology_description.md) – Architecture, prerequisites, and security model
- [User Guide](docs/user_guide.md) – Configuration and daily operation
- [API Reference](docs/api.md) – Programmatic interfaces

## Requirements

- Linux (Ubuntu 20.04+, Debian 11+, or RHEL 8+)
- Python 3.10 or higher
- 8GB RAM minimum (16GB recommended for AI models)
- 10GB free disk space (more for document storage)

## Security

Sophia Learner implements defense-in-depth security:
- Sandboxed document parsing with resource limits
- Macro and script stripping from Office documents
- Optional ClamAV integration for virus scanning
- Quarantine system for suspicious files
- No data leaves your infrastructure

## Contributing

See [CONTRIBUTING.md](docs/CONTRIBUTING.md) for guidelines.
4. **`development_guide.md`** – Setting up dev environment, adding new parsers, testing

Would you like me to proceed with any of these, or should we begin coding the actual modules as per the prioritization plan?
