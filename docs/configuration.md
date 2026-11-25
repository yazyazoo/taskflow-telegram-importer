# Configuration

Copy `config.example.yml` to the untracked `config.yml`. Unknown and missing
keys are rejected at startup.

## Telegram

`api_id`, `api_hash`, and `bot_token` authenticate the Telethon bot session.
`session_path` is the persistent MTProto session file; its parent must be
writable and survive restarts. Keep real credentials only in untracked
`config.yml`.

`progress_refresh_seconds` controls persisted progress and Telegram panel
updates; it does not delay downloads. `max_concurrent_downloads` bounds active
MTProto transfers globally; additional files remain queued.
`allowed_user_ids` contains the numeric IDs of authorized operators. Only their
private chats are accepted.

The repository example uses two active transfers and a 30-second refresh.

## TaskFlow WebUI

`taskflow.webui_url` is the HTTPS address opened by the Telegram `/taskflow`
command. Authentication remains inside the normal TaskFlow WebUI login; the
importer never appends the access token to the URL.

## Paths and files

`paths.staging` and `paths.gate` must be absolute, distinct, non-nested, and on
the same filesystem. TaskFlow monitors only the gate. `paths.log_file` is the
internal importer log.

`files.allowed_extensions` defines phase-one video types. Matching is case
insensitive. `minimum_free_gib` is the free-space reserve left after staging a
file. There is intentionally no 7z setting yet.

All operational paths, extensions, timeouts, user IDs, reserves, URLs, and log
levels belong in `config.yml`; source code contains no deployment values.
