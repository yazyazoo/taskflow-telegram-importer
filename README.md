# TaskFlow Telegram Importer

Private Telegram-to-filesystem importer for TaskFlow.

The service receives forwarded video files through a locally hosted Telegram
Bot API server, persists import sessions, and publishes only complete files to
TaskFlow's existing filesystem integration gate. It does not call TaskFlow APIs
or create workflows.

Phase-one implementation is available: private-chat authorization, persistent
sessions, concurrent Telegram acquisition, crash recovery, atomic filesystem
publication, and operator-driven retry/exclusion/deletion. The importer never
calls TaskFlow APIs.

Local automated checks are not a substitute for the required final seedbox
test with the official local Bot API and real Telegram files.

## Documentation

- [Configuration](docs/configuration.md)
- [Deployment](docs/deployment.md)
- [Operations](docs/operations.md)

The Italian overview is available in [`docs/it/README.md`](docs/it/README.md).

