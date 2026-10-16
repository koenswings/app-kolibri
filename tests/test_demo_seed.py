"""Unit tests for the IDEA demo seed (demo/build_users_csv.py, demo/users.csv,
demo/provision-demo.sh). Run: python3 -m unittest discover -s tests -p 'test_*.py'"""
import csv
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "demo"))
import build_users_csv as b  # noqa: E402

USERS = os.path.join(ROOT, "demo", "users.csv")
SCRIPT = os.path.join(ROOT, "demo", "provision-demo.sh")
# Header row exactly as Kolibri 0.15.5 bulkexportusers writes it (locale en).
EXPORT_HDR = ("Database ID (UUID),Username (USERNAME),Password (PASSWORD),Full name (FULL_NAME),"
              "User type (USER_TYPE),Identifier (IDENTIFIER),Birth year (BIRTH_YEAR),Gender (GENDER),"
              "Learner enrollment (ENROLLED_IN),Coach assignment (ASSIGNED_TO)")


class UsersCsv(unittest.TestCase):
    def setUp(self):
        self.rows = b.read_rows(USERS)

    def test_header_is_015_format(self):
        with open(USERS) as f:
            self.assertEqual(next(csv.reader(f)), b.FIELDS)

    def test_accounts_and_passwords(self):
        names = [r["USERNAME"] for r in self.rows]
        self.assertEqual(names, ["teacher1", "teacher2", "learner1", "learner2", "learner3"])
        for r in self.rows:  # learners too: stored fallback <account>911!
            self.assertEqual(r["PASSWORD"], r["USERNAME"] + "911!")

    def test_roles_and_class(self):
        for t in self.rows[:2]:  # teacher1, teacher2: coaches of Grade 5
            self.assertEqual((t["USER_TYPE"], t["ASSIGNED_TO"], t["ENROLLED_IN"]), ("CLASS_COACH", "Grade 5", ""))
        for r in self.rows[2:]:
            self.assertEqual((r["USER_TYPE"], r["ENROLLED_IN"], r["ASSIGNED_TO"]), ("LEARNER", "Grade 5", ""))
            self.assertIn(r["USER_TYPE"], ("LEARNER", "ADMIN", "FACILITY_COACH", "CLASS_COACH"))

    def test_no_uuid_in_template(self):
        self.assertTrue(all(r["UUID"] == "" for r in self.rows))


class Build(unittest.TestCase):
    def setUp(self):
        self.desired = b.read_rows(USERS)
        self.tmp = tempfile.mkdtemp()
        self.export = os.path.join(self.tmp, "e.csv")
        with open(self.export, "w") as f:
            f.write(EXPORT_HDR + "\n")
            f.write("aaa,teacher1,*,Teacher One,CLASS_COACH,,,,,Grade 5\n")
            f.write("bbb,learner1,*,Learner One,LEARNER,,,,Grade 5,\n")
            f.write("ccc,someoneelse,*,X,LEARNER,,,,Other,\n")

    def test_fresh_device(self):
        out = {r["USERNAME"]: r for r in b.build(self.desired, [])}
        self.assertTrue(all(r["UUID"] == "" for r in out.values()))
        for n in ("teacher1", "teacher2", "learner1", "learner2", "learner3"):
            self.assertEqual(out[n]["PASSWORD"], n + "911!")
        self.assertFalse(any("nopw" in r["PASSWORD"] for r in out.values()))

    def test_rerun_keeps_passwords_and_reuses_uuid(self):
        out = {r["USERNAME"]: r for r in b.build(self.desired, b.read_rows(self.export))}
        self.assertEqual((out["teacher1"]["UUID"], out["teacher1"]["PASSWORD"]), ("aaa", "*"))
        self.assertEqual((out["learner1"]["UUID"], out["learner1"]["PASSWORD"]), ("bbb", "*"))
        self.assertEqual((out["learner2"]["UUID"], out["learner2"]["PASSWORD"]), ("", "learner2911!"))
        self.assertNotIn("someoneelse", out)  # other users are never touched

    def test_force_passwords(self):
        out = {r["USERNAME"]: r for r in b.build(self.desired, b.read_rows(self.export), True)}
        self.assertEqual((out["teacher1"]["UUID"], out["teacher1"]["PASSWORD"]), ("aaa", "teacher1911!"))
        # --force-passwords also resets the learners' stored fallback
        self.assertEqual((out["learner1"]["UUID"], out["learner1"]["PASSWORD"]), ("bbb", "learner1911!"))

    def test_rejects_non_scheme_password(self):
        bad = [dict(self.desired[0], PASSWORD="random-Xy7#")]
        with self.assertRaises(ValueError):
            b.build(bad, [])

    def test_learner_needs_911_fallback(self):
        for pw in ("", "random-Xy7#"):
            with self.assertRaises(ValueError):
                b.build([dict(self.desired[2], PASSWORD=pw)], [])

    def test_teacher_still_needs_911(self):
        for t in self.desired[:2]:
            with self.assertRaises(ValueError):
                b.build([dict(t, PASSWORD="")], [])

    def test_cli_roundtrip(self):
        out = os.path.join(self.tmp, "o.csv")
        self.assertEqual(b.main([USERS, self.export, out]), 0)
        rows = b.read_rows(out)
        self.assertEqual(len(rows), 5)
        with open(out) as f:
            self.assertEqual(next(csv.reader(f)), b.FIELDS)


class Script(unittest.TestCase):
    def dry(self, *extra):
        d = tempfile.mkdtemp()
        return subprocess.run(["bash", SCRIPT, "--dry-run", *extra, d], capture_output=True, text=True,
                              env=dict(os.environ, DOCKER="false"))

    def test_dry_run_uses_only_supported_commands(self):
        p = self.dry()
        self.assertEqual(p.returncode, 0, p.stderr)
        cmds = [l for l in p.stdout.splitlines() if l.startswith("DRY:")]
        self.assertEqual(len(cmds), 5)
        for c in cmds:
            self.assertIn(" run --rm --network none ", c)
        for c in (cmds[0], cmds[2]):  # read-only probe
            self.assertIn("facility_info.py", c)
        for c, sub in zip(cmds[1:2] + cmds[3:], ["provisiondevice", "bulkexportusers", "bulkimportusers"]):
            self.assertIn(" manage " + sub, c)
        pd = cmds[1]
        self.assertIn("--noinput", pd)
        self.assertIn("--preset formal", pd)
        self.assertIn("--facility_settings /seed/facility_settings.json", pd)
        self.assertIn("admin911\\!", pd)
        # users always go to IDEA Demo School explicitly
        self.assertIn("bulkexportusers --facility FACILITY_ID", cmds[3])
        self.assertIn("bulkimportusers --facility FACILITY_ID", cmds[4])

    def test_never_shell_or_exec(self):
        with open(SCRIPT) as f:
            src = "\n".join(l for l in f if not l.lstrip().startswith("#"))
        self.assertNotIn("manage shell", src)
        self.assertNotIn(" exec ", src)
        self.assertNotIn("--delete", src)

    def test_bad_option(self):
        self.assertEqual(self.dry("--nope").returncode, 2)


import facility_info as fi  # noqa: E402
import sqlite3  # noqa: E402


class FacilityInfo(unittest.TestCase):
    def make(self, provisioned, facilities):
        d = tempfile.mkdtemp()
        con = sqlite3.connect(os.path.join(d, "db.sqlite3"))
        con.execute("CREATE TABLE device_devicesettings (id INTEGER, is_provisioned BOOL)")
        con.execute("INSERT INTO device_devicesettings VALUES (1, ?)", (int(provisioned),))
        con.execute("CREATE TABLE kolibriauth_collection (id TEXT, name TEXT, kind TEXT)")
        for i, (n, k) in enumerate(facilities):
            con.execute("INSERT INTO kolibriauth_collection VALUES (?, ?, ?)", ("id%d" % i, n, k))
        con.commit(); con.close()
        return d

    def test_empty_dir(self):
        self.assertEqual(fi.probe(tempfile.mkdtemp(), "IDEA Demo School"), (False, ""))

    def test_other_facility_only(self):
        d = self.make(True, [("Other School", "facility"), ("Grade 5", "classroom")])
        self.assertEqual(fi.probe(d, "IDEA Demo School"), (True, ""))

    def test_finds_demo_facility_not_a_class(self):
        d = self.make(True, [("Other School", "facility"), ("idea demo school", "classroom"),
                             ("IDEA Demo School", "facility")])
        self.assertEqual(fi.probe(d, "IDEA Demo School"), (True, "id2"))

    def test_ambiguous_refused(self):
        d = self.make(True, [("IDEA Demo School", "facility"), ("Idea Demo School", "facility")])
        with self.assertRaises(SystemExit):
            fi.probe(d, "IDEA Demo School")

    def test_opens_read_only(self):
        with open(os.path.join(ROOT, "demo", "facility_info.py")) as f:
            self.assertIn("mode=ro", f.read())

    def test_read_only(self):
        d = self.make(True, [("IDEA Demo School", "facility")])
        os.chmod(os.path.join(d, "db.sqlite3"), 0o444)
        self.assertEqual(fi.probe(d, "IDEA Demo School"), (True, "id0"))


if __name__ == "__main__":
    unittest.main()
