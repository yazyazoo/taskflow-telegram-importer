# Operations

Forward an optional poster/caption and one or more video files to the bot.
Every file starts downloading immediately. Press
`Ho finito di inoltrare · N file` to seal collection; this does not wait for
downloads. Confirm or edit the proposed title/year. Complete files are then
published atomically to the TaskFlow filesystem gate.

The service keeps one collecting session per operator and permits multiple
sealed/downloading sessions. JSON manifests under staging retain Telegram file
IDs and exact owned paths. Restart recovery leaves complete files untouched
and restarts only incomplete acquisitions.

For a failed file, use retry or exclude. Deleting an entire session first
cancels active jobs, then removes only manifest-recorded staging and published
paths. Because the importer intentionally does not ask TaskFlow whether files
were claimed, deleting a published session can remove files already in use;
the operator must verify this before confirming deletion.

Internal levels are:

- `DEBUG`: paths, decisions, and state transitions;
- `INFO`: session milestones, counts, and durations;
- `WARNING`: recovered or degraded outcomes;
- `ERROR`: terminal file/session failures.

Tokens and Telegram application credentials are always redacted. Phase one
does not extract 7z archives and does not create TaskFlow workflows.
