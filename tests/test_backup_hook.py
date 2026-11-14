"""Unit tests for hooks/backup-pre.sh and hooks/backup-post.sh (idea#403).
Run: python3 -m unittest tests.test_backup_hook   (or python3 -m pytest tests/test_backup_hook.py)
Real SQLite files in WAL mode, with a writer committing while the preHook copies."""
from __future__ import print_function

import json
import os
import sqlite3
import subprocess
import tempfile
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRE = os.path.join(ROOT, "hooks", "backup-pre.sh")
POST = os.path.join(ROOT, "hooks", "backup-post.sh")
DBS = ("db", "job_storage", "notifications", "networklocation", "sessions", "syncqueue")


def make_db(path, rows=50):
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    con.executemany("INSERT INTO t (v) VALUES (?)", [("x" * 200,)] * rows)
    con.commit()
    return con  # kept open, so the -wal/-shm stay like a running Kolibri


def make_jobs(path, jobs):
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute('CREATE TABLE "jobs" ("id" varchar(36) NOT NULL PRIMARY KEY, "state" varchar(20) NOT NULL, '
                '"func" varchar(200) NOT NULL, "priority" integer NOT NULL, "queue" varchar(50) NOT NULL, '
                '"saved_job" text NOT NULL)')
    for i, (func, state) in enumerate(jobs):
        con.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?)", (str(i), state, func, 10, "content", "{}"))
    con.commit()
    return con


def run(script, home):
    env = dict(os.environ, KOLIBRI_HOME=home)
    return subprocess.run(["sh", script], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          universal_newlines=True, timeout=120)


class BackupHookTest(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="kol-bk-")
        self.cons = []
        for n in DBS:
            if n == "job_storage":
                self.cons.append(make_jobs(os.path.join(self.home, n + ".sqlite3"), []))
            else:
                self.cons.append(make_db(os.path.join(self.home, n + ".sqlite3")))
        self.out = os.path.join(self.home, "idea-backup")

    def tearDown(self):
        for c in self.cons:
            c.close()

    def test_copies_every_db_consistent_while_a_writer_commits(self):
        stop = threading.Event()
        committed = []

        def writer():
            con = sqlite3.connect(os.path.join(self.home, "db.sqlite3"), timeout=30)
            while not stop.is_set():
                con.execute("INSERT INTO t (v) VALUES ('w')")
                con.commit()
                committed.append(1)
            con.close()

        th = threading.Thread(target=writer)
        th.start()
        time.sleep(0.2)
        try:
            r = run(PRE, self.home)
        finally:
            stop.set()
            th.join()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(committed, "the writer committed during the copy")
        names = sorted(os.listdir(self.out))
        self.assertEqual(names, sorted([n + ".sqlite3" for n in DBS] + ["MANIFEST.json"]))
        for n in DBS:
            c = sqlite3.connect(os.path.join(self.out, n + ".sqlite3"))
            self.assertEqual(c.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(c.execute("PRAGMA journal_mode").fetchone()[0], "delete")  # one self-contained file
            c.close()
        c = sqlite3.connect(os.path.join(self.out, "db.sqlite3"))
        self.assertGreaterEqual(c.execute("SELECT count(*) FROM t").fetchone()[0], 50)
        c.close()
        m = json.load(open(os.path.join(self.out, "MANIFEST.json")))
        self.assertEqual(m["format"], "idea-kolibri-backup/1")
        self.assertEqual(sorted(d["db"] for d in m["databases"]), sorted(n + ".sqlite3" for n in DBS))
        self.assertTrue(all(d["integrity"] == "ok" for d in m["databases"]))
        # the live files are untouched and still in WAL mode
        self.assertTrue(os.path.exists(os.path.join(self.home, "db.sqlite3-wal")))

    def test_running_import_exits_3_and_writes_nothing(self):
        for func, state in (("kolibri.core.content.tasks.remotecontentimport", "RUNNING"),
                            ("kolibri.core.content.tasks.diskchannelimport", "SELECTED"),
                            ("kolibri.core.content.tasks.deletechannel", "CANCELING")):
            jp = os.path.join(self.home, "job_storage.sqlite3")
            self.cons[DBS.index("job_storage")].execute("DELETE FROM jobs")
            self.cons[DBS.index("job_storage")].execute(
                "INSERT INTO jobs VALUES ('a', ?, ?, 10, 'content', '{}')", (state, func))
            self.cons[DBS.index("job_storage")].commit()
            r = run(PRE, self.home)
            self.assertEqual(r.returncode, 3, (func, state, r.stderr))
            self.assertIn("short stop", r.stderr)
            self.assertFalse(os.path.exists(self.out), "no copies when falling back")
            self.assertTrue(os.path.exists(jp))

    def test_queued_or_finished_imports_and_other_tasks_do_not_block(self):
        jc = self.cons[DBS.index("job_storage")]
        jc.executemany("INSERT INTO jobs VALUES (?, ?, ?, 10, 'q', '{}')", [
            ("1", "QUEUED", "kolibri.core.content.tasks.remotecontentimport"),
            ("2", "COMPLETED", "kolibri.core.content.tasks.diskcontentimport"),
            ("3", "FAILED", "kolibri.core.content.tasks.remotechannelimport"),
            ("4", "RUNNING", "kolibri.core.auth.tasks.peerfacilitysync"),
            ("5", "RUNNING", "kolibri.core.content.tasks.remotechanneldiffstats"),
        ])
        jc.commit()
        r = run(PRE, self.home)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_not_a_kolibri_home_fails(self):
        for c in self.cons:
            c.close()
        self.cons = []
        os.rename(os.path.join(self.home, "db.sqlite3"), os.path.join(self.home, "elsewhere"))
        r = run(PRE, self.home)
        self.assertEqual(r.returncode, 1)
        self.assertIn("no db.sqlite3", r.stderr)

    def test_unreadable_database_fails_nonzero(self):
        bad = os.path.join(self.home, "broken.sqlite3")
        with open(bad, "wb") as f:
            f.write(b"this is not a database" * 100)
        r = run(PRE, self.home)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("broken.sqlite3", r.stderr + r.stdout + str(os.listdir(self.out)))
        self.assertFalse(os.path.exists(os.path.join(self.out, "broken.sqlite3")))

    def test_extra_db_copied_test_db_skipped_and_stale_tmp_replaced(self):
        self.cons.append(make_db(os.path.join(self.home, "future.sqlite3")))
        self.cons.append(make_db(os.path.join(self.home, "test_job_storage.sqlite3")))
        os.makedirs(self.out)
        with open(os.path.join(self.out, "db.sqlite3.tmp"), "w") as f:
            f.write("leftover")
        r = run(PRE, self.home)
        self.assertEqual(r.returncode, 0, r.stderr)
        names = os.listdir(self.out)
        self.assertIn("future.sqlite3", names)
        self.assertNotIn("test_job_storage.sqlite3", names)
        self.assertFalse([n for n in names if n.endswith(".tmp")])

    def test_post_removes_copies_only_and_is_idempotent(self):
        self.assertEqual(run(PRE, self.home).returncode, 0)
        with open(os.path.join(self.home, "keep.txt"), "w") as f:
            f.write("x")
        r = run(POST, self.home)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(self.out))
        for n in DBS:
            self.assertTrue(os.path.exists(os.path.join(self.home, n + ".sqlite3")))
        self.assertTrue(os.path.exists(os.path.join(self.home, "keep.txt")))
        r = run(POST, self.home)
        self.assertEqual(r.returncode, 0)
        self.assertIn("nothing to remove", r.stdout)

    def test_post_after_a_failed_pre_leaves_no_partial_copy(self):
        os.makedirs(self.out)
        for n in ("db.sqlite3.tmp", "db.sqlite3.tmp-journal", "MANIFEST.json.tmp"):
            open(os.path.join(self.out, n), "w").close()
        r = run(POST, self.home)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(self.out))

    def test_post_keeps_a_foreign_file_and_the_folder(self):
        self.assertEqual(run(PRE, self.home).returncode, 0)
        with open(os.path.join(self.out, "operator-note.txt"), "w") as f:
            f.write("not ours")
        r = run(POST, self.home)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(os.listdir(self.out), ["operator-note.txt"])


if __name__ == "__main__":
    unittest.main()
