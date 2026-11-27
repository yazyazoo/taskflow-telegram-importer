# Operations

Forward an optional poster/caption and one or more video files to the bot. No
download starts while the session is collecting. Press
`Ho finito di inoltrare · N file`, then select one branch:

- `Finalizza con WebUI TaskFlow` downloads and publishes the files; the
  operator completes workflow creation in the existing mobile WebUI;
- `Quick Workflow` asks for media kind, title/year, TMDB candidate, TaskFlow
  preset and optional cleanup/sub-ita overrides before downloads start.

After the operator selects a TMDB search result, the importer reads that
record's localized details. At least one named genre is required before the
Quick Workflow can continue. The selected TMDB ID and genres remain visible in
the persisted Telegram session; TaskFlow still receives the canonical TMDB ID
and resolves its own task output.

After Quick downloads complete, the importer publishes to the filesystem gate,
requests integration reconciliation, reads the resulting package IDs, and only
then calls TaskFlow Create and Start. The workflow ID returned by TaskFlow is
shown in the Telegram session.

The service keeps one collecting session per operator and permits multiple
sealed/downloading sessions. JSON manifests under staging retain Telegram
message IDs, progress, workflow draft, and exact owned paths. Restart recovery
leaves complete files untouched and restarts only incomplete acquisitions whose
branch configuration was confirmed.

For a failed file, use retry or exclude. Deleting an entire session first
cancels active jobs, then removes only manifest-recorded staging and published
paths. Published files may already be in use by TaskFlow, so the operator must
verify this before confirming deletion.

Internal levels are:

- `DEBUG`: paths, decisions, and state transitions;
- `INFO`: session milestones, counts, and durations;
- `WARNING`: recovered or degraded outcomes;
- `ERROR`: terminal file/session failures.

Before downloading, the collecting-session panel lists every file in arrival
order with the exact Telegram resolution, duration, estimated average bitrate,
and size. Missing Telegram metadata is shown as unavailable and never blocks
the session. This inspection does not download media bytes.

The status panel also lists every active, queued, complete, failed, or excluded
file. Active transfers show bytes, percentage, speed, and ETA at the configured
refresh interval. Credentials are redacted from logs. The importer does not
extract 7z archives yet.
