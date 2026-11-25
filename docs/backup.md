# Backup hooks (idea#403)

Kolibri declares `x-app.backup` with `method: hook`, so an Engine backup (`backupApp`, a scheduled
Backup Disk run, or an `immediate` dock) copies the instance **while Kolibri keeps running**. The
contract is the Engine's (agent-engine-dev#325, idea#444; `docs/COMMANDS.md` `backupApp`).

## What happens

1. **preHook** `docker compose exec -T kolibri /hooks/backup-pre.sh` (300 s limit).
   **Exit codes:** 0 = copies written. **Any non-zero exit, or a timeout, is a failed preHook** to the
   Engine: it runs the postHook and then takes the `fallback` path (`stop`: a short stop, recorded as
   `HOOK_FALLBACK`). The codes below are a convention for people reading the logs, not something the
   Engine tells apart: **3 = a channel content task is running**, 1 = any other error.
   **updateApp:** the pre-update backup forces `fallback: fail` (idea#448), so an update started while an
   import runs is refused with `HOOK_FAILED`; Kolibri is not stopped. Retry the update after the import.
   - If a channel content task is running (`SELECTED`, `RUNNING` or `CANCELING` in `job_storage.sqlite3`
     `jobs`: disk/remote channel or content import, `remoteimport`, `diskimport`, automatic resource
     import, `deletechannel`), it exits **3** (proposal §3.5). The stop interrupts the running task.
   - **Queued** imports don't block: they haven't started and would run after a stop as well. One may
     start while borg runs, so that archive can hold half-imported channel content. That is accepted:
     channel content is re-importable, the databases come from the copies taken before, and the next
     run packs a clean state.
   - It refuses (exit 1) if `$KOLIBRI_HOME` has a top-level `*.sqlite3` other than the six known
     databases (`test_*` excepted). Its live file would be packed with no consistent copy, so `KNOWN` in
     `hooks/backup-pre.sh` and `x-app.backup.hookExclude` must be updated first.
   - It refuses (exit 1) if the free space in `$KOLIBRI_HOME` is below the databases' size (each db plus
     its `-wal`) + 10 % + a 32 MiB margin (`IDEA_BACKUP_MIN_FREE_MARGIN`, bytes).
   - Otherwise it copies the six databases (`db`, `job_storage`, `notifications`, `networklocation`,
     `sessions`, `syncqueue`) with SQLite's **online backup API** into
     `data/kolibri/idea-backup/<name>.sqlite3`. Each copy is one self-contained file (journal mode
     DELETE), passes `PRAGMA integrity_check`, is fsynced and only then renamed into place.
     `MANIFEST.json` lists the copies, sizes, timings, the source size and the free space before.
   - Any other error exits 1.
2. **borg** packs the instance folder. `hookExclude` keeps the live databases and their `-wal`, `-shm`
   and `-journal` out of a hook archive (24 entries, one per file; #325 allows no globs). `exclude` always drops
   `data/kolibri/process_cache` (Kolibri's diskcache, rebuilt on start). Channel content is packed.
3. **postHook** `/hooks/backup-post.sh` removes the copies and `MANIFEST.json` (and any `.tmp`
   leftovers), then the folder if it is empty. It also runs after a failed preHook. A failure is only
   a warning (`HOOK_POST_WARNING`); the next preHook replaces any leftover.

On `HOOK_FALLBACK` the Engine stops Kolibri, drops `hookExclude` and packs the stopped live databases.
An archive therefore holds either the copies (hook) or the live databases (fallback), never neither.

## Restore

The Engine extracts the archive and starts the instance; it does not apply the copies. `kolibri-start.sh`
does it, before anything else after the mount check: for each `idea-backup/<db>.sqlite3` whose live
`<db>.sqlite3` is **missing**, it renames the copy into place (a stray `-wal`/`-shm`/`-journal` of that database is
renamed `….pre-restore-<UTC stamp>` first, never deleted). An existing live database is never replaced.
After a fallback archive there is no `idea-backup/`, so nothing happens. `.env` is in every archive, so
`port`, `port_zip` and `MORANGO_SYSTEM_ID` stay the same.

## verifyBackup

`verify.present` / `verify.absent` list only paths that hold for both a hook and a fallback archive
(`.env`, `data/kolibri/.data_version`, `data/kolibri/options.ini`, `hooks/backup-pre.sh` present;
`data/kolibri/process_cache` absent). The Engine can't tell the two apart: the archive name is only a
timestamp, and the hook result is recorded only on the backup operation (`op.args.hookResult`). So
**verifyBackup checks no database yet**, neither the copies nor the live files. That waits for an Engine
follow-up (Axle) that tags each archive with its hook result. Until then, use
`listBackup <instance> <disk> <archive>` to see whether an archive has the copies.

## Pre-update snapshots (`snapshotExclude`)

A Backup Disk archive **does pack channel content** (`data/kolibri/content`). The
pre-update snapshot taken by `updateApp` does not: compose.yaml sets

```yaml
x-app:
  snapshotExclude:
    - data/kolibri/content   # channel content: large and re-importable
```

Learner data lives in the SQLite databases under `data/kolibri/` (not in
`content/`). Those databases stay in the snapshot so a rollback can restore
them. Channel files are content-addressed and can be imported again.

`updateApp` also merges `x-app.backup.exclude` (`data/kolibri/process_cache`)
into that snapshot list. Paths must be under `data/`, with no globs, and at
most 32 entries (Engine `backupExclude.ts`). See agent-app-dev
`docs/compose-conventions.md`.

## Tests

`tests/test_backup_hook.py` (real WAL databases, a writer committing during the copy, import cases,
postHook) and `tests/backup-hook.test.mjs` (the compose block and the restore step).
