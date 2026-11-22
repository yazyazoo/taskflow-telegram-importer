# Configuration

Copy `config.example.yml` to the untracked `config.yml`. Unknown and missing
keys are rejected at startup.

## Telegram

`telegram.api_base_url` is the local Bot API base URL ending in `/bot`.
`local_mode` must remain enabled so `getFile` returns a local absolute path.
`long_poll_request_timeout_seconds` controls the open long-poll request; new
updates still return immediately. `allowed_user_ids` contains the numeric IDs
of authorized operators. Only their private chats are accepted.

The BotFather token is resolved by executing, without a shell:

```text
<token_command.executable> <token_command.alias> <token_command.field>
```

Store the token in Vaultwarden and expose only the allowlisted alias through
`rp-secret`. Command output, stderr, and token values are never included in
configuration errors.

## Paths and files

`paths.staging` and `paths.gate` must be absolute, distinct, non-nested, and on
the same filesystem. TaskFlow monitors only the gate. `paths.log_file` is the
internal importer log.

`files.allowed_extensions` defines phase-one video types. Matching is case
insensitive. `minimum_free_gib` is the free-space reserve left after staging a
file. There is intentionally no 7z setting in phase one.

All operational paths, extensions, timeouts, user IDs, reserves, URLs, and log
levels belong in `config.yml`; source code contains no deployment values.
