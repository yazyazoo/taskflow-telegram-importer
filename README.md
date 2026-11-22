# TaskFlow Telegram Importer

Private Telegram-to-filesystem importer for TaskFlow.

The service receives forwarded video files through a locally hosted Telegram
Bot API server, persists import sessions, and publishes only complete files to
TaskFlow's existing filesystem integration gate. It does not call TaskFlow APIs
or create workflows.

Status: design and implementation planning.

The Italian overview is available in [`docs/it/README.md`](docs/it/README.md).

