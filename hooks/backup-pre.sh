#!/bin/sh
# hooks/backup-pre.sh: Kolibri backup preHook (idea#403, Engine x-app.backup method: hook).
# The Engine runs it before borg, without stopping Kolibri:
#   docker compose exec -T kolibri /hooks/backup-pre.sh
# It writes a consistent copy of every Kolibri SQLite database in $KOLIBRI_HOME (db, job_storage,
# notifications, networklocation, sessions, syncqueue; all in WAL mode) to $KOLIBRI_HOME/idea-backup/
# with SQLite's online backup API, checks each copy with PRAGMA integrity_check, and only then moves
# it into place. borg packs the copies; x-app.backup.hookExclude keeps the live files out of a hook
# archive. kolibri-start.sh puts a copy back only when its live database is missing (restore).
#
# Exit codes: 0 = copies written. ANY non-zero exit (or a timeout) is a failed preHook to the Engine:
# it runs hooks/backup-post.sh and then takes the x-app.backup.fallback path (here `stop`: a short stop,
# HOOK_FALLBACK). By convention 3 = a channel content task (import or channel delete) is running, and
# 1 = any other error (unknown database, too little free space, a failed copy or integrity check).
# Inside updateApp's pre-update backup the Engine forces fallback: fail, so an update during an import
# is refused with HOOK_FAILED instead of stopping Kolibri (idea#448).
# The Engine always runs hooks/backup-post.sh afterwards, which removes the copies.
if command -v python3 >/dev/null 2>&1; then PY=python3
elif command -v python >/dev/null 2>&1; then PY=python
else echo "backup-pre: python not found" >&2; exit 1
fi
exec "$PY" - "$@" <<'PY'
import glob
import json
import os
import shutil
import sqlite3
import sys
import time

HOME = os.environ.get("KOLIBRI_HOME") or "/root/.kolibri"
OUT = os.path.join(HOME, "idea-backup")
# Kolibri 0.19.5 kolibri/deployment/default/sqlite_db_names.py: "default" plus ADDITIONAL_SQLITE_DATABASES.
# Keep in step with x-app.backup.hookExclude in compose.yaml.
KNOWN = ("db", "job_storage", "notifications", "networklocation", "sessions", "syncqueue")
# Tasks that change channel content on disk (kolibri/core/content/tasks.py, 0.19.5).
CONTENT_TASKS = tuple("kolibri.core.content.tasks." + f for f in (
    "diskchannelimport", "diskcontentimport", "diskimport",
    "remotechannelimport", "remotecontentimport", "remoteresourceimport", "remoteimport",
    "automatic_resource_import", "automatic_synchronize_content_requests_and_import",
    "deletechannel",
))
# QUEUED jobs do not block: they have not started and would run after a stop too. One may start
# during borg; it only touches channel content, which is re-importable (packed as-is, next run is clean).
ACTIVE = ("SELECTED", "RUNNING", "CANCELING")
# Free space needed in $KOLIBRI_HOME beyond the databases' own size (db + -wal per database).
MARGIN = int(os.environ.get("IDEA_BACKUP_MIN_FREE_MARGIN") or 32 * 1024 * 1024)


def err(msg):
    sys.stderr.write("backup-pre: %s\n" % msg)


def active_content_jobs():
    path = os.path.join(HOME, "job_storage.sqlite3")
    if not os.path.exists(path):
        return []
    con = sqlite3.connect(path, timeout=30)
    try:
        con.execute("PRAGMA busy_timeout=30000")
        q = "SELECT func, state FROM jobs WHERE state IN (%s) AND func IN (%s)" % (
            ",".join("?" * len(ACTIVE)), ",".join("?" * len(CONTENT_TASKS)))
        return con.execute(q, ACTIVE + CONTENT_TASKS).fetchall()
    except sqlite3.OperationalError as e:
        if "no such table" in str(e):
            return []
        raise
    finally:
        con.close()


class Refuse(Exception):
    pass


def databases():
    """The known databases present. Any other top-level *.sqlite3 (except test_*) refuses: its live
    file would be packed next to no copy, so x-app.backup.hookExclude and KNOWN must be updated first."""
    names = [n + ".sqlite3" for n in KNOWN if os.path.exists(os.path.join(HOME, n + ".sqlite3"))]
    known = set(n + ".sqlite3" for n in KNOWN)
    unknown = sorted(os.path.basename(p) for p in glob.glob(os.path.join(HOME, "*.sqlite3"))
                     if os.path.basename(p) not in known and not os.path.basename(p).startswith("test_"))
    if unknown:
        raise Refuse("unknown database(s) %s in %s: add them to KNOWN in hooks/backup-pre.sh and to "
                     "x-app.backup.hookExclude (with -wal, -shm, -journal) before a hook backup"
                     % (", ".join(unknown), HOME))
    return names


def check_space(names):
    total = 0
    for n in names:
        for suffix in ("", "-wal"):
            f = os.path.join(HOME, n + suffix)
            if os.path.exists(f):
                total += os.path.getsize(f)
    need = total + total // 10 + MARGIN
    free = shutil.disk_usage(HOME).free
    if free < need:
        raise Refuse("not enough free space in %s for the copies: %d bytes free, %d needed "
                     "(databases %d + 10%% + margin %d)" % (HOME, free, need, total, MARGIN))
    return total, free


def snapshot(name):
    src_path = os.path.join(HOME, name)
    final = os.path.join(OUT, name)
    tmp = final + ".tmp"
    for f in (tmp, tmp + "-journal", tmp + "-wal", tmp + "-shm"):
        if os.path.exists(f):
            os.remove(f)  # our own leftover from an interrupted run, never a live file
    t0 = time.time()
    src = sqlite3.connect(src_path, timeout=60)
    dst = sqlite3.connect(tmp)
    try:
        src.execute("PRAGMA busy_timeout=60000")
        src.backup(dst)  # one step: a consistent snapshot of the committed state, WAL included
        # A copy of a WAL database is in WAL mode too; make it one self-contained file.
        dst.execute("PRAGMA journal_mode=DELETE")
        res = [r[0] for r in dst.execute("PRAGMA integrity_check").fetchall()]
        if res != ["ok"]:
            raise RuntimeError("integrity_check of the copy of %s: %s" % (name, "; ".join(res[:5])))
    finally:
        dst.close()
        src.close()
    fd = os.open(tmp, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, final)
    return {"db": name, "bytes": os.path.getsize(final), "seconds": round(time.time() - t0, 2), "integrity": "ok"}


def main():
    if not os.path.isfile(os.path.join(HOME, "db.sqlite3")):
        err("no db.sqlite3 in %s; not a Kolibri home" % HOME)
        return 1
    try:
        names = databases()
    except Refuse as e:
        err(str(e))
        return 1
    jobs = active_content_jobs()
    if jobs:
        err("channel content task running (%s); exit 3 so the Engine takes a short stop instead"
            % ", ".join("%s=%s" % (f.rsplit(".", 1)[-1], s) for f, s in jobs))
        return 3
    try:
        total, free = check_space(names)
    except Refuse as e:
        err(str(e))
        return 1
    if not os.path.isdir(OUT):
        os.makedirs(OUT, 0o700)
    t0 = time.time()
    done = [snapshot(n) for n in names]
    manifest = {"format": "idea-kolibri-backup/1", "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "seconds": round(time.time() - t0, 2), "sourceBytes": total, "freeBytesBefore": free,
                "databases": done}
    tmp = os.path.join(OUT, "MANIFEST.json.tmp")
    with open(tmp, "w") as f:
        json.dump(manifest, f, indent=1, sort_keys=True)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, os.path.join(OUT, "MANIFEST.json"))
    print(json.dumps(manifest, sort_keys=True))
    return 0


try:
    sys.exit(main())
except SystemExit:
    raise
except Exception as e:  # any failure: non-zero, the Engine runs the postHook and falls back
    err("%s: %s" % (type(e).__name__, e))
    sys.exit(1)
PY
