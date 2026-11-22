# Deployment

Deploy the private repository under the configured seedbox application path
and create a virtual environment from `pyproject.toml`.

Two independent Supervisor programs are required:

1. `telegram-bot-api`: the official Telegram Bot API server with `--local`;
2. `taskflow-telegram-importer`: this Python service, started with
   `taskflow-telegram-importer --project-root <deployment-directory>`.

The local Bot API needs Telegram `api_id` and `api_hash`; the importer needs
the BotFather token. Keep all three in Vaultwarden and resolve them through
separate allowlisted `rp-secret` aliases. Do not place them in Supervisor
configuration, repository files, command-line arguments, or logs.

Before moving a bot from Telegram's cloud Bot API to the local server, call
the official `logOut` method once and wait for it to complete. The importer
uses long polling, so no public webhook or inbound port is needed.

Grant both services read/write access to staging. Grant the importer
read/write access to the TaskFlow filesystem gate. Keep staging outside every
TaskFlow watched directory. Staging and gate must share a filesystem because
publication uses atomic rename.

Start and verify `telegram-bot-api` before the importer. A deployment is not
accepted until a real single video, a real multi-file set, and a restart during
active transfers have been tested on the seedbox.
