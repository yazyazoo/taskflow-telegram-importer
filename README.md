# TaskFlow Telegram Importer

Private Telegram-to-filesystem importer for TaskFlow.

The service receives forwarded video files through Telethon/MTProto, persists
import sessions, and publishes only complete files to TaskFlow's existing
filesystem integration gate. The manual branch stops there; the Quick Workflow
prototype resolves TMDB metadata, reconciles TaskFlow filesystem package IDs,
then creates and starts a preset-backed workflow through the TaskFlow API.

Downloads start only after collection is sealed and the operator selects a
branch. The Quick Workflow draft is persisted before acquisition starts.

Local automated checks are not a substitute for the required final seedbox
test with real Telegram files over MTProto.

## Documentation

- [Configuration](docs/configuration.md)
- [Deployment](docs/deployment.md)
- [Operations](docs/operations.md)

The Italian overview is available in [`docs/it/README.md`](docs/it/README.md).

