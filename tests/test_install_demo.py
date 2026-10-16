"""Unit tests for demo/install-demo.sh with a stub Engine (no docker, no Engine).
Run: python3 -m unittest discover -s tests -p 'test_*.py'"""
import json
import os
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "demo", "install-demo.sh")

STUB = r'''#!/usr/bin/env bash
# stub engine-cmd: list -> $STATE/list.json ; send -> log, installApp adds the instance
echo "$*" >> "$STATE/calls"
case "$1" in
  list) cat "$STATE/list.json" ;;
  send) shift; cmd="$*"
        if [[ "$cmd" == installApp* ]]; then cp "$STATE/after.json" "$STATE/list.json"; mkdir -p "$STATE/disks/sdb1/instances/kolibri-new/data/kolibri"
          printf 'x-app:\n  instanceName: Kolibri-Demo\n' > "$STATE/disks/sdb1/instances/kolibri-new/compose.yaml"
          printf 'port=1\nhostname=h\nip=1.2.3.4\n' > "$STATE/disks/sdb1/instances/kolibri-new/.env"; fi ;;
esac
'''


def inst(i, name):
    return {"id": i, "name": name, "status": "Running", "port": 1, "storedOn": "d1", "device": "sdb1", "diskName": "D"}


class InstallDemo(unittest.TestCase):
    def setUp(self):
        self.s = tempfile.mkdtemp()
        stub = os.path.join(self.s, "ec.sh")
        open(stub, "w").write(STUB); os.chmod(stub, 0o755)
        for n in ("prov.sh", "docker.sh"):
            p = os.path.join(self.s, n)
            open(p, "w").write('#!/usr/bin/env bash\necho "%s $*" >> "$STATE/calls"\n' % n); os.chmod(p, 0o755)
        self.ch = os.path.join(self.s, "ch", "KOLIBRI_DATA", "content", "databases")
        os.makedirs(self.ch)
        for c in ("aaa", "bbb", "ccc"):
            open(os.path.join(self.ch, c + ".sqlite3"), "w").close()
        self.set_list([inst("kolibri-other", "kolibri-demo"), inst("kolibri-x", "kolibri")])
        json.dump([inst("kolibri-other", "kolibri-demo"), inst("kolibri-new", "Kolibri-Demo")],
                  open(os.path.join(self.s, "after.json"), "w"))

    def set_list(self, l):
        json.dump(l, open(os.path.join(self.s, "list.json"), "w"))

    def run_it(self, *args):
        env = dict(os.environ, STATE=self.s, ENGINE_CMD=os.path.join(self.s, "ec.sh"),
                   PROVISION=os.path.join(self.s, "prov.sh"), DOCKER=os.path.join(self.s, "docker.sh"),
                   DISKS_ROOT=os.path.join(self.s, "disks"), PATH="/usr/bin:/bin", HTTP_WAIT="1")
        return subprocess.run(["bash", SCRIPT, "--channels", os.path.join(self.s, "ch"), *args],
                              capture_output=True, text=True, env=env)

    def calls(self):
        p = os.path.join(self.s, "calls")
        return open(p).read().splitlines() if os.path.exists(p) else []

    def test_name_must_be_one_word_with_demo(self):
        for n in ("Kolibri Demo", "kolibri", "school;rm"):
            self.assertEqual(self.run_it("--name", n, "--disk", "d1").returncode, 2, n)
        self.assertEqual(self.calls(), [])

    def test_install_needs_disk(self):
        self.assertEqual(self.run_it().returncode, 2)
        self.assertFalse(any(c.startswith("send") for c in self.calls()))

    def test_ambiguous_refused_before_any_command(self):
        self.set_list([inst("a", "Kolibri-Demo"), inst("b", "Kolibri-Demo")])
        self.assertEqual(self.run_it("--disk", "d1").returncode, 12)
        self.assertFalse(any(c.startswith("send") for c in self.calls()))

    def test_exact_name_only(self):
        # 'kolibri-demo' (another instance) is NOT 'Kolibri-Demo': a new install happens
        p = self.run_it("--disk", "d1")
        c = self.calls()
        self.assertIn("send installApp kolibri-latest d1 --name Kolibri-Demo", c)
        self.assertFalse(any("kolibri-other" in x for x in c))
        # full flow on the new instance: stop, seed, 3x2 imports, start (then HTTP fails in the stub: 17)
        self.assertIn("send stopInstance kolibri-new d1", c)
        self.assertTrue(any(x.startswith("prov.sh --demo-instance") and x.endswith("kolibri-new/data/kolibri") for x in c))
        self.assertEqual(sum("disk.sh" in x or ("docker.sh run" in x and " import" in x) for x in c), 6)
        self.assertIn("send startInstance kolibri-new d1", c)
        self.assertEqual(p.returncode, 17, p.stderr)

    def test_reuse_no_second_install(self):
        self.set_list([inst("kolibri-new", "Kolibri-Demo")])
        d = os.path.join(self.s, "disks/sdb1/instances/kolibri-new")
        os.makedirs(d + "/data/kolibri")
        open(d + "/compose.yaml", "w").write("x-app:\n  instanceName: Kolibri-Demo\n")
        open(d + "/.env", "w").write("port=1\n")
        self.run_it()
        c = self.calls()
        self.assertFalse(any("installApp" in x for x in c))
        self.assertIn("send stopInstance kolibri-new d1", c)

    def test_refuses_when_compose_name_differs(self):
        self.set_list([inst("kolibri-new", "Kolibri-Demo")])
        d = os.path.join(self.s, "disks/sdb1/instances/kolibri-new")
        os.makedirs(d + "/data/kolibri")
        open(d + "/compose.yaml", "w").write("x-app:\n  instanceName: kolibri\n")
        p = self.run_it()
        self.assertEqual(p.returncode, 13)
        self.assertFalse(any("stopInstance" in x for x in self.calls()))

    def test_refuses_other_disk(self):
        self.set_list([inst("kolibri-new", "Kolibri-Demo")])
        self.assertEqual(self.run_it("--disk", "elsewhere").returncode, 13)
        self.assertFalse(any("stopInstance" in x for x in self.calls()))


if __name__ == "__main__":
    unittest.main()
