# Security Checklist

- `.env` is ignored by git.
- `.env.example` contains no real secrets.
- Upload size is bounded by environment configuration.
- File type validation uses content signatures.
- FFmpeg and FFprobe calls avoid shell execution.
- Storage keys are resolved inside the storage root to prevent path traversal.
- Local temporary directories are cleaned by context managers.
- Telegram tokens are read only from environment variables.
- Phase 0 does not publish database, cache, or object-storage ports.
