# Deployment

Deploy the private repository under the configured seedbox application path
and create a virtual environment from `pyproject.toml`.

One Supervisor program is required:

1. `taskflow-telegram-importer`: this Python service, started with
   `taskflow-telegram-importer --project-root <deployment-directory>`.

Telethon needs Telegram `api_id`, `api_hash`, and the BotFather token. Store the
real values only in the untracked runtime configuration. The MTProto client
maintains one persistent session file and needs no public webhook or inbound
port.

Grant the importer read/write access to staging, its MTProto session directory,
and the TaskFlow filesystem gate. Keep staging outside every
TaskFlow watched directory. Staging and gate must share a filesystem because
publication uses atomic rename.

A deployment is not accepted until a real single video, a real multi-file set,
live speed/ETA updates, and a restart during active transfers have been tested
on the seedbox.
