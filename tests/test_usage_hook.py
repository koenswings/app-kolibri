"""Unit tests for hooks/usage.sh (idea#413). Run: python3 -m unittest tests.test_usage_hook"""
from __future__ import print_function

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(ROOT, "hooks", "usage.sh")
DAY = "2026-11-12"
FORBIDDEN = {
    "engine", "instance", "name", "listed", "clock",
    "collectedAt", "hookStatus", "skipReason",
}


def run_hook(home, args, extra_env=None):
    env = os.environ.copy()
    env["KOLIBRI_HOME"] = home
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["sh", HOOK] + list(args),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=env, timeout=20,
    )


def run_piped(home, args):
    env = os.environ.copy()
    env["KOLIBRI_HOME"] = home
    with open(HOOK, "rb") as fh:
        script = fh.read()
    return subprocess.run(
        ["sh", "-s", "--"] + list(args),
        input=script, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=env, timeout=20,
    )


def parse(proc):
    out = proc.stdout.decode("utf-8")
    err = proc.stderr.decode("utf-8")
    obj = json.loads(out)
    return obj, out, err


def create_schema(conn, visitor_id=False):
    conn.executescript("""
    CREATE TABLE kolibriauth_collection (
        id TEXT PRIMARY KEY, name TEXT, kind TEXT, parent_id TEXT
    );
    CREATE TABLE kolibriauth_facilityuser (
        id TEXT PRIMARY KEY, username TEXT, date_joined TEXT,
        facility_id TEXT, deleted INTEGER DEFAULT 0, date_deleted TEXT
    );
    CREATE TABLE kolibriauth_role (
        id TEXT PRIMARY KEY, user_id TEXT, collection_id TEXT, kind TEXT
    );
    CREATE TABLE kolibriauth_membership (
        id TEXT PRIMARY KEY, user_id TEXT, collection_id TEXT
    );
    CREATE TABLE device_devpermissions (
        user_id TEXT PRIMARY KEY, is_superuser INTEGER, can_manage_content INTEGER
    );
    CREATE TABLE logger_usersessionlog (
        id TEXT PRIMARY KEY, user_id TEXT, start_timestamp TEXT,
        last_interaction_timestamp TEXT
    );
    CREATE TABLE logger_contentsessionlog (
        id TEXT PRIMARY KEY, user_id TEXT, content_id TEXT, channel_id TEXT,
        start_timestamp TEXT, end_timestamp TEXT, time_spent REAL,
        progress REAL, kind TEXT""" + (", visitor_id TEXT" if visitor_id else "") + """
    );
    CREATE TABLE logger_contentsummarylog (
        id TEXT PRIMARY KEY, user_id TEXT, content_id TEXT, channel_id TEXT,
        completion_timestamp TEXT, time_spent REAL, progress REAL, kind TEXT
    );
    CREATE TABLE lessons_lesson (
        id TEXT PRIMARY KEY, title TEXT, is_active INTEGER,
        date_created TEXT, created_by_id TEXT, collection_id TEXT, resources TEXT
    );
    CREATE TABLE exams_exam (
        id TEXT PRIMARY KEY, title TEXT, active INTEGER, archive INTEGER,
        date_created TEXT, date_activated TEXT, date_archived TEXT,
        creator_id TEXT, collection_id TEXT
    );
    """)
    conn.commit()


def fill_channel_db(path, channel_id, channel_name, nodes):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE content_channelmetadata (id TEXT, name TEXT)")
    conn.execute("INSERT INTO content_channelmetadata VALUES (?, ?)", (channel_id, channel_name))
    conn.execute("CREATE TABLE content_contentnode (id TEXT, content_id TEXT, title TEXT, kind TEXT, channel_id TEXT)")
    for node in nodes:
        conn.execute(
            "INSERT INTO content_contentnode VALUES (?, ?, ?, ?, ?)",
            (node["id"], node["content_id"], node["title"], node["kind"], channel_id),
        )
    conn.commit()
    conn.close()


class UsageHookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "db.sqlite3")

    def connect(self):
        conn = sqlite3.connect(self.db)
        create_schema(conn)
        return conn

    def test_sample_unsupported(self):
        proc = run_hook(self.tmp, ["sample"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        obj, out, err = parse(proc)
        self.assertEqual(obj, {"schema": "idea-usage-sample/1", "app": "kolibri", "supported": False})
        self.assertTrue(FORBIDDEN.isdisjoint(obj))
        self.assertEqual(out.count("{"), 1)

    def test_invalid_args(self):
        proc = run_hook(self.tmp, ["day", "not-a-date"])
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(proc.stdout, b"")
        self.assertIn(b"invalid", proc.stderr)

    def test_day_metrics_and_assigned(self):
        conn = self.connect()
        conn.execute("INSERT INTO kolibriauth_collection VALUES ('fac1','West School','facility',NULL)")
        conn.execute("INSERT INTO kolibriauth_collection VALUES ('cls1','Grade 5','classroom','fac1')")
        conn.executemany(
            "INSERT INTO kolibriauth_facilityuser VALUES (?,?,?,?,0,NULL)",
            [
                ("u-admin", "admin", "2026-01-01 00:00:00", "fac1"),
                ("u-teach", "teacher1", "2026-01-02 00:00:00", "fac1"),
                ("u-l1", "ann", "2026-11-12 09:00:00", "fac1"),
                ("u-l2", "bob", "2026-10-01 00:00:00", "fac1"),
            ],
        )
        conn.execute("INSERT INTO device_devpermissions VALUES ('u-admin', 1, 1)")
        conn.execute("INSERT INTO kolibriauth_role VALUES ('r1','u-teach','cls1','coach')")
        conn.execute("INSERT INTO kolibriauth_membership VALUES ('m1','u-l1','cls1')")
        conn.execute("INSERT INTO kolibriauth_membership VALUES ('m2','u-l2','cls1')")
        conn.execute(
            "INSERT INTO logger_usersessionlog VALUES ('s1','u-l1','2026-11-12 10:00:00','2026-11-12 10:20:00')"
        )
        conn.execute(
            "INSERT INTO logger_usersessionlog VALUES ('s2','u-teach','2026-11-12 11:00:00','2026-11-12 11:10:00')"
        )
        conn.execute(
            "INSERT INTO logger_usersessionlog VALUES ('s-old','u-l2','2026-11-11 10:00:00','2026-11-11 10:30:00')"
        )
        conn.execute(
            "INSERT INTO logger_contentsessionlog VALUES (?,?,?,?,?,?,?,?,?)",
            ("c1", "u-l1", "cid-video", "chan-1", "2026-11-12 10:05:00",
             "2026-11-12 10:15:00", 600, 1.0, "video"),
        )
        conn.execute(
            "INSERT INTO logger_contentsessionlog VALUES (?,?,?,?,?,?,?,?,?)",
            ("c-guest", None, "cid-video", "chan-1", "2026-11-12 12:00:00",
             "2026-11-12 12:05:00", 120, 0.2, "video"),
        )
        conn.execute(
            "INSERT INTO logger_contentsummarylog VALUES (?,?,?,?,?,?,?,?)",
            ("sum1", "u-l1", "cid-video", "chan-1", "2026-11-12 10:15:00", 600, 1.0, "video"),
        )
        conn.execute(
            "INSERT INTO lessons_lesson VALUES (?,?,?,?,?,?,?)",
            ("les1", "Fractions", 1, "2026-11-12 08:00:00", "u-teach", "cls1",
             json.dumps([{"content_id": "cid-video", "channel_id": "chan-1"}])),
        )
        conn.execute(
            "INSERT INTO exams_exam VALUES (?,?,?,?,?,?,?,?,?)",
            ("ex1", "Quiz 1", 1, 0, "2026-11-12 08:30:00", "2026-11-12 09:00:00", None, "u-teach", "cls1"),
        )
        conn.commit()
        conn.close()
        fill_channel_db(
            os.path.join(self.tmp, "content", "databases", "chan-1.sqlite3"),
            "chan-1", "Maths",
            [{"id": "n1", "content_id": "cid-video", "title": "Adding fractions", "kind": "video"}],
        )
        proc = run_hook(self.tmp, ["day", DAY])
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        obj, out, err = parse(proc)
        self.assertTrue(FORBIDDEN.isdisjoint(obj), obj)
        self.assertNotIn("teacher1", out)
        self.assertNotIn("u-admin", out)
        self.assertNotIn("u-l1", out)
        self.assertNotIn("u-teach", out)
        self.assertNotIn('"username"', out)
        self.assertEqual(obj["schema"], "idea-usage-day/1")
        self.assertEqual(obj["day"], DAY)
        self.assertEqual(obj["app"], "kolibri")
        self.assertFalse(obj["demo"])
        self.assertEqual(obj["setup"]["classes"], 1)
        self.assertEqual(obj["setup"]["classesDelta"], 0)
        self.assertEqual(obj["setup"]["learner"], {"total": 2, "beyondSeed": 2})
        self.assertEqual(obj["setup"]["learnerDelta"], 1)
        self.assertEqual(obj["setup"]["learnerEnrolled"], 2)
        self.assertEqual(obj["setup"]["teacher"], {"total": 1, "beyondSeed": 0})
        self.assertEqual(obj["setup"]["coach"], {"total": 1, "beyondSeed": 0})
        self.assertEqual(obj["setup"]["admin"], {"total": 1, "beyondSeed": 0})
        self.assertNotIn("teachers", obj["setup"])
        self.assertNotIn("admins", obj["setup"])
        self.assertNotIn("learnersRegistered", obj["setup"])
        self.assertEqual(obj["signins"]["learner"], {"total": 1, "beyondSeed": 1, "sessions": 1, "minutes": 20})
        self.assertEqual(obj["signins"]["coach"], {"total": 1, "beyondSeed": 0, "sessions": 1, "minutes": 10})
        self.assertEqual(obj["signins"]["admin"], {"total": 0, "beyondSeed": 0, "sessions": 0, "minutes": 0})
        self.assertEqual(obj["guest"]["visits"], 1)
        self.assertEqual(obj["guest"]["seconds"], 120)
        self.assertEqual(len(obj["content"]), 1)
        row = obj["content"][0]
        self.assertEqual(row["channel"], "Maths")
        self.assertEqual(row["title"], "Adding fractions")
        self.assertEqual(row["kind"], "video")
        self.assertEqual(row["role"], "learner")
        self.assertEqual(row["visits"], 1)
        self.assertEqual(row["seconds"], 600)
        self.assertEqual(row["completions"], 1)
        self.assertTrue(row["assigned"])
        self.assertEqual(obj["teaching"]["lessonsCreated"], 1)
        self.assertEqual(obj["teaching"]["lessonsVisible"], 1)
        self.assertEqual(obj["teaching"]["quizzesCreated"], 1)
        self.assertEqual(obj["teaching"]["quizzesStarted"], 1)
        self.assertEqual(obj["teaching"]["quizzesEnded"], 0)

    def test_missing_db_emits_empty_coach(self):
        proc = run_hook(self.tmp, ["day", DAY])
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        obj, _, _ = parse(proc)
        self.assertEqual(obj["setup"]["coach"], {"total": 0, "beyondSeed": 0})
        self.assertEqual(obj["setup"]["admin"], {"total": 0, "beyondSeed": 0})
        self.assertEqual(obj["setup"]["teacher"], {"total": 0, "beyondSeed": 0})
        self.assertEqual(obj["setup"]["learner"], {"total": 0, "beyondSeed": 0})

    def test_setup_coach_includes_admin_excludes_seed_and_counts_once(self):
        # setup.coach is every account holding a coach role, admins included.
        # beyondSeed uses the same teacher1/teacher2 seed list as setup.teacher.
        conn = self.connect()
        conn.execute("INSERT INTO kolibriauth_collection VALUES ('fac1','West School','facility',NULL)")
        conn.execute("INSERT INTO kolibriauth_collection VALUES ('cls1','Grade 5','classroom','fac1')")
        conn.executemany(
            "INSERT INTO kolibriauth_facilityuser VALUES (?,?,?,?,?,?)",
            [
                ("u-admin-coach", "head", "2026-01-01 00:00:00", "fac1", 0, None),
                ("u-admin-only", "admin", "2026-01-01 00:00:00", "fac1", 0, None),
                ("u-plain", "mina", "2026-01-02 00:00:00", "fac1", 0, None),
                ("u-both", "sam", "2026-01-03 00:00:00", "fac1", 0, None),
                ("u-learner", "ann", "2026-01-04 00:00:00", "fac1", 0, None),
                ("u-seed1", "teacher1", "2026-01-05 00:00:00", "fac1", 0, None),
                ("u-seed2", "teacher2", "2026-01-06 00:00:00", "fac1", 0, None),
                ("u-gone", "gone", "2026-01-07 00:00:00", "fac1", 1, "2026-02-01 00:00:00"),
            ],
        )
        conn.execute("INSERT INTO device_devpermissions VALUES ('u-admin-coach', 1, 1)")
        conn.execute("INSERT INTO device_devpermissions VALUES ('u-admin-only', 1, 1)")
        conn.executemany(
            "INSERT INTO kolibriauth_role VALUES (?,?,?,?)",
            [
                ("r-admin-coach", "u-admin-coach", "fac1", "coach"),
                ("r-admin-role", "u-admin-only", "fac1", "admin"),
                ("r-plain", "u-plain", "fac1", "coach"),
                ("r-both-fac", "u-both", "fac1", "coach"),
                ("r-both-cls", "u-both", "cls1", "classroom assignable coach"),
                ("r-seed1", "u-seed1", "fac1", "coach"),
                ("r-seed2", "u-seed2", "cls1", "classroom assignable coach"),
                ("r-gone", "u-gone", "fac1", "coach"),
            ],
        )
        conn.commit()
        conn.close()
        proc = run_hook(self.tmp, ["day", DAY])
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        obj, out, _ = parse(proc)
        self.assertTrue(FORBIDDEN.isdisjoint(obj), obj)
        self.assertNotIn("head", out)
        self.assertNotIn("teacher1", out)
        self.assertNotIn("mina", out)
        # admin+coach counts; plain coach counts; learner does not;
        # seeds are in total only; class+facility coach counts once; deleted excluded.
        self.assertEqual(obj["setup"]["coach"], {"total": 5, "beyondSeed": 3})
        # existing highest-role fields stay unchanged
        self.assertEqual(obj["setup"]["admin"], {"total": 2, "beyondSeed": 1})
        self.assertEqual(obj["setup"]["teacher"], {"total": 4, "beyondSeed": 2})
        self.assertEqual(obj["setup"]["learner"], {"total": 1, "beyondSeed": 1})

    def test_setup_coach_underscore_class_role_kind(self):
        # 0.15.5 and 0.19.5 store "classroom assignable coach"; also accept the underscore alias.
        conn = self.connect()
        conn.execute("INSERT INTO kolibriauth_collection VALUES ('fac1','West School','facility',NULL)")
        conn.execute("INSERT INTO kolibriauth_collection VALUES ('cls1','Grade 5','classroom','fac1')")
        conn.execute(
            "INSERT INTO kolibriauth_facilityuser VALUES ('u-cls','pat','2026-01-01 00:00:00','fac1',0,NULL)"
        )
        conn.execute(
            "INSERT INTO kolibriauth_role VALUES ('r1','u-cls','cls1','classroom_assignable_coach')"
        )
        conn.commit()
        conn.close()
        proc = run_hook(self.tmp, ["day", DAY])
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        obj, _, _ = parse(proc)
        self.assertEqual(obj["setup"]["coach"], {"total": 1, "beyondSeed": 1})
        self.assertEqual(obj["setup"]["teacher"], {"total": 1, "beyondSeed": 1})

    def test_demo_seed_exclusion_by_id_not_username(self):
        conn = self.connect()
        conn.execute("INSERT INTO kolibriauth_collection VALUES ('demo-fac','IDEA Demo School','facility',NULL)")
        conn.execute("INSERT INTO kolibriauth_collection VALUES ('real-fac','West School','facility',NULL)")
        conn.executemany(
            "INSERT INTO kolibriauth_facilityuser VALUES (?,?,?,?,0,NULL)",
            [
                ("seed-l3", "learner3", "2026-01-01 00:00:00", "demo-fac"),
                ("real-l3", "learner3", "2026-01-01 00:00:00", "real-fac"),
                ("demo-other", "learner1", "2026-01-01 00:00:00", "demo-fac"),
            ],
        )
        conn.execute(
            "INSERT INTO logger_contentsessionlog VALUES (?,?,?,?,?,?,?,?,?)",
            ("ex-seed", "seed-l3", "cid-ex", "chan-1", "2026-11-12 10:00:00",
             "2026-11-12 10:05:00", 50, 1.0, "exercise"),
        )
        conn.execute(
            "INSERT INTO logger_contentsessionlog VALUES (?,?,?,?,?,?,?,?,?)",
            ("vid-seed", "seed-l3", "cid-vid", "chan-1", "2026-11-12 10:10:00",
             "2026-11-12 10:12:00", 30, 0.4, "video"),
        )
        conn.execute(
            "INSERT INTO logger_contentsessionlog VALUES (?,?,?,?,?,?,?,?,?)",
            ("ex-real", "real-l3", "cid-ex", "chan-1", "2026-11-12 11:00:00",
             "2026-11-12 11:05:00", 40, 1.0, "exercise"),
        )
        conn.commit()
        conn.close()
        proc = run_hook(self.tmp, ["day", DAY])
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        obj, out, _ = parse(proc)
        self.assertTrue(obj["demo"])
        self.assertNotIn("learner3", out)
        kinds = {(c["kind"], c["visits"], c["seconds"]) for c in obj["content"]}
        # seed learner3 exercise dropped; their video kept; real-school learner3 exercise kept
        self.assertIn(("video", 1, 30), kinds)
        self.assertIn(("exercise", 1, 40), kinds)
        self.assertFalse(any(c["kind"] == "exercise" and c["seconds"] == 50 for c in obj["content"]))

    def test_shared_account_flag(self):
        conn = self.connect()
        conn.execute("INSERT INTO kolibriauth_collection VALUES ('fac1','West School','facility',NULL)")
        conn.execute("INSERT INTO kolibriauth_facilityuser VALUES ('only','kid','2026-01-01 00:00:00','fac1',0,NULL)")
        for i in range(3):
            conn.execute(
                "INSERT INTO logger_usersessionlog VALUES (?,?,?,?)",
                ("s%d" % i, "only", "2026-11-12 10:0%d:00" % i, "2026-11-12 10:1%d:00" % i),
            )
        conn.commit()
        conn.close()
        obj, _, _ = parse(run_hook(self.tmp, ["day", DAY]))
        self.assertIn("sharedLearnerAccount", obj["flags"])

    def test_piped_stdin_matches_file_exec(self):
        conn = self.connect()
        conn.execute("INSERT INTO kolibriauth_collection VALUES ('fac1','X','facility',NULL)")
        conn.commit()
        conn.close()
        a = parse(run_hook(self.tmp, ["day", DAY]))[0]
        b = parse(run_piped(self.tmp, ["day", DAY]))[0]
        self.assertEqual(a, b)

    def test_env_mode_and_day(self):
        proc = run_hook(self.tmp, [], extra_env={"IDEA_USAGE_MODE": "sample"})
        obj, _, _ = parse(proc)
        self.assertEqual(obj["schema"], "idea-usage-sample/1")


if __name__ == "__main__":
    unittest.main()
