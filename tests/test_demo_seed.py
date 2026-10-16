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
        self.assertEqual(names, ["teacher1", "learner1", "learner2", "learner3"])
        for r in self.rows:
            if r["USER_TYPE"] == "LEARNER":
                self.assertEqual(r["PASSWORD"], "", "learners have no password")
            else:
                self.assertEqual(r["PASSWORD"], r["USERNAME"] + "911!")

    def test_roles_and_class(self):
        t = self.rows[0]
        self.assertEqual((t["USER_TYPE"], t["ASSIGNED_TO"], t["ENROLLED_IN"]), ("CLASS_COACH", "Grade 5", ""))
        for r in self.rows[1:]:
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
        self.assertEqual(out["teacher1"]["PASSWORD"], "teacher1911!")
        for n in ("learner1", "learner2", "learner3"):
            pw = out[n]["PASSWORD"]
            # bulkimportusers 0.15.5 needs a non-empty password: unknown placeholder, never 911!
            self.assertTrue(pw.startswith("nopw-") and len(pw) > 20, pw)
            self.assertNotIn("911", pw)
        self.assertNotEqual(out["learner1"]["PASSWORD"], out["learner2"]["PASSWORD"])

    def test_rerun_keeps_passwords_and_reuses_uuid(self):
        out = {r["USERNAME"]: r for r in b.build(self.desired, b.read_rows(self.export))}
        self.assertEqual((out["teacher1"]["UUID"], out["teacher1"]["PASSWORD"]), ("aaa", "*"))
        self.assertEqual((out["learner1"]["UUID"], out["learner1"]["PASSWORD"]), ("bbb", "*"))
        self.assertEqual(out["learner2"]["UUID"], "")
        self.assertTrue(out["learner2"]["PASSWORD"].startswith("nopw-"))
        self.assertNotIn("someoneelse", out)  # other users are never touched

    def test_force_passwords(self):
        out = {r["USERNAME"]: r for r in b.build(self.desired, b.read_rows(self.export), True)}
        self.assertEqual((out["teacher1"]["UUID"], out["teacher1"]["PASSWORD"]), ("aaa", "teacher1911!"))
        # learners never get a password, even with --force-passwords
        self.assertEqual((out["learner1"]["UUID"], out["learner1"]["PASSWORD"]), ("bbb", "*"))

    def test_rejects_non_scheme_password(self):
        bad = [dict(self.desired[0], PASSWORD="random-Xy7#")]
        with self.assertRaises(ValueError):
            b.build(bad, [])

    def test_rejects_learner_password(self):
        bad = [dict(self.desired[1], PASSWORD="learner1911!")]
        with self.assertRaises(ValueError):
            b.build(bad, [])

    def test_teacher_still_needs_911(self):
        bad = [dict(self.desired[0], PASSWORD="")]
        with self.assertRaises(ValueError):
            b.build(bad, [])

    def test_cli_roundtrip(self):
        out = os.path.join(self.tmp, "o.csv")
        self.assertEqual(b.main([USERS, self.export, out]), 0)
        rows = b.read_rows(out)
        self.assertEqual(len(rows), 4)
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
        self.assertEqual(len(cmds), 3)
        for c, sub in zip(cmds, ["provisiondevice", "bulkexportusers", "bulkimportusers"]):
            self.assertIn(" run --rm --network none ", c)
            self.assertIn(" manage " + sub, c)
        self.assertIn("--noinput", cmds[0])
        self.assertIn("--preset formal", cmds[0])
        self.assertIn("--facility_settings /seed/facility_settings.json", cmds[0])
        self.assertIn("admin911\\!", cmds[0])

    def test_never_shell_or_exec(self):
        with open(SCRIPT) as f:
            src = "\n".join(l for l in f if not l.lstrip().startswith("#"))
        self.assertNotIn("manage shell", src)
        self.assertNotIn(" exec ", src)
        self.assertNotIn("--delete", src)

    def test_bad_option(self):
        self.assertEqual(self.dry("--nope").returncode, 2)


if __name__ == "__main__":
    unittest.main()
