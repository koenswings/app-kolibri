# Backup hooks (idea#403)

Kolibri declares `x-app.backup` with `method: hook`, so an Engine backup (`backupApp`, a scheduled
Backup Disk run, or an `immediate` dock) copies the instance **while Kolibri keeps running**. The
contract is the Engine's (agent-engine-dev#325, idea#444; `docs/COMMANDS.md` `backupApp`).

## What happens

1. **preHook** `docker compose exec -T kolibri /hooks/backup-pre.sh` (300 s limit):
   - If a channel content task is running (`SELECTED`, `RUNNING` or `CANCELING` in `job_storage.sqlite3`
     `jobs`: disk/remote channel or content import, `remoteimport`, `diskimport`, automatic resource
     import, `deletechannel`), it exits **3**. The Engine runs the postHook and then falls back to the
     short stop for this run (`fallback: stop`, recorded as `HOOK_FALLBACK`; proposal §3.5). Queued
     jobs don't block: they start after the stop as well. The stop interrupts the running task.
   - Otherwise it copies every SQLite database in `$KOLIBRI_HOME` (`db`, `job_storage`, `notifications`,
     `networklocation`, `sessions`, `syncqueue`, plus any other top-level `*.sqlite3` except `test_*`)
     with SQLite's **online backup API** into `data/kolibri/idea-backup/<name>.sqlite3`. Each copy is
     one self-contained file (journal mode DELETE), passes `PRAGMA integrity_check`, is fsynced and only
     then renamed into place. `MANIFEST.json` lists the copies, sizes and timings.
   - Any other error exits 1: the Engine falls back to the short stop.
2. **borg** packs the instance folder. `hookExclude` keeps the live databases and their `-wal`/`-shm`
   out of a hook archive (one entry per file; #325 allows no globs). `exclude` always drops
   `data/kolibri/process_cache` (Kolibri's diskcache, rebuilt on start). Channel content is packed.
3. **postHook** `/hooks/backup-post.sh` removes the copies and `MANIFEST.json` (and any `.tmp`
   leftovers), then the folder if it is empty. It also runs after a failed preHook. A failure is only
   a warning (`HOOK_POST_WARNING`); the next preHook replaces any leftover.

On `HOOK_FALLBACK` the Engine stops Kolibri, drops `hookExclude` and packs the stopped live databases.
An archive therefore holds either the copies (hook) or the live databases (fallback), never neither.

## Restore

The Engine extracts the archive and starts the instance; it does not apply the copies. `kolibri-start.sh`
does it, before anything else after the mount check: for each `idea-backup/<db>.sqlite3` whose live
`<db>.sqlite3` is **missing**, it renames the copy into place (a stray `-wal`/`-shm` of that database is
renamed `….pre-restore-<UTC stamp>` first, never deleted). An existing live database is never replaced.
After a fallback archive there is no `idea-backup/`, so nothing happens. `.env` is in every archive, so
`port`, `port_zip` and `MORANGO_SYSTEM_ID` stay the same.

## verifyBackup

`verify.present` / `verify.absent` list only paths that hold for both a hook and a fallback archive
(`.env`, `data/kolibri/.data_version`, `data/kolibri/options.ini`, `hooks/backup-pre.sh` present;
`data/kolibri/process_cache` absent). Use `listBackup <instance> <disk> <archive>` to see whether an
archive has the copies.

## Tests

`tests/test_backup_hook.py` (real WAL databases, a writer committing during the copy, import cases,
postHook) and `tests/backup-hook.test.mjs` (the compose block and the restore step).
