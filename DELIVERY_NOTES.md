# TG-Radar Final Consolidated Build

## This pass focused on
- Dual Telegram clients for interaction vs worker traffic
- APScheduler daily maintenance jobs with jitter and idle gating
- ACK-first interaction flow for mutating/heavy commands
- Simpler alert cards with less noise
- Rule append semantics for `-addrule`
- Pure `config.json` + `config.schema.json`
- Better observability for command intake and reply failures

## Key behavior changes
- `-sync`, `-routescan`, `-update`, `-restart` now acknowledge immediately and then continue in background.
- `-addrule`, `-setrule`, `-delrule`, `-enable`, `-disable`, `-setnotify`, `-setalert`, `-setprefix`, `-addroute`, `-delroute` now show an immediate "已接收，开始执行，请稍等…" panel before continuing.
- `-addrule` appends terms into the same rule name instead of overwriting the old pattern. Use `-setrule` for full replacement.
- Default alert cards no longer show Chat ID / Message ID. Sender username is formatted as `@username` when available.
- Daily maintenance is driven by APScheduler rather than short-period hot polling. Config/logic changes still trigger immediate Core reload via signal/job.
- `-jobs` shows queued/running background jobs and includes a trace id when available.

## Observability
New or improved log actions:
- `CMD_ACCEPTED`
- `CMD_ACK`
- `CMD_REPLY_FAIL`
- `JOB_QUEUE`
- `JOB_START`
- `JOB_DONE`
- `JOB_FAIL`

## Verification performed
- `python -m compileall -q src`
- `bash -n install.sh`
- `bash -n deploy.sh`

## Important honesty note
This package has been statically checked, but it has not been end-to-end tested against a live Telegram account inside this environment.
