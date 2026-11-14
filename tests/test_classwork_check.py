"""Unit tests for the classwork_check.py live-demo guard.

Run: python3 -m unittest discover -s tests -p 'test_*.py'
"""
import io
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import classwork_check as cc  # noqa: E402


class UrlPort(unittest.TestCase):
    def test_explicit_and_default_ports(self):
        self.assertEqual(cc.url_port("http://127.0.0.1:56462"), 56462)
        self.assertEqual(cc.url_port("http://127.0.0.1:18090/learn"), 18090)
        self.assertEqual(cc.url_port("https://example:18091"), 18091)
        self.assertEqual(cc.url_port("http://127.0.0.1"), 80)
        self.assertEqual(cc.url_port("https://example"), 443)


class DockerPsParse(unittest.TestCase):
    def test_matches_published_port_only(self):
        out = "\n".join([
            "kid-kolibri-demo-kolibri-1\t0.0.0.0:18090->8080/tcp, 0.0.0.0:18091->8081/tcp",
            "throwaway-kolibri-1\t0.0.0.0:56462->8080/tcp",
            "other\t",
        ])
        self.assertEqual(cc.names_from_docker_ps(out, 18090), ["kid-kolibri-demo-kolibri-1"])
        self.assertEqual(cc.names_from_docker_ps(out, 56462), ["throwaway-kolibri-1"])
        self.assertEqual(cc.names_from_docker_ps(out, 19999), [])
        self.assertEqual(cc.names_from_docker_ps("", 18090), [])


class LiveDemoReasons(unittest.TestCase):
    def reasons(self, url, **kw):
        kw.setdefault("environ", {})
        kw.setdefault("docker_names", [])
        return cc.live_demo_reasons(url, **kw)

    def test_refuses_reserved_ports(self):
        for port in (18090, 18091):
            r = self.reasons("http://127.0.0.1:%s" % port)
            self.assertTrue(any("port %s" % port in x for x in r), r)

    def test_allows_other_ports(self):
        self.assertEqual(self.reasons("http://127.0.0.1:56462"), [])
        self.assertEqual(self.reasons("http://100.126.117.80:19999"), [])

    def test_refuses_container_name_exact_or_containing(self):
        r = self.reasons("http://127.0.0.1:56462", container="kid-kolibri-demo")
        self.assertTrue(any("kid-kolibri-demo" in x for x in r), r)
        r = self.reasons("http://127.0.0.1:56462", container="kid-kolibri-demo-kolibri-1")
        self.assertTrue(any("kid-kolibri-demo-kolibri-1" in x for x in r), r)

    def test_allows_other_demo_instance_names(self):
        # throwaway demos often have "demo" in the name; only the live instance is refused
        self.assertEqual(self.reasons("http://127.0.0.1:56462", container="kolibri-demo"), [])
        self.assertEqual(self.reasons("http://127.0.0.1:56462", container="kolibri-st9ddvr2mf957oebpgv"), [])

    def test_refuses_url_host_containing_live_name(self):
        r = self.reasons("http://kid-kolibri-demo:56462")
        self.assertTrue(any("URL" in x and "kid-kolibri-demo" in x for x in r), r)

    def test_refuses_env_names(self):
        for key in ("COMPOSE_PROJECT_NAME", "IDEA_INSTANCE_ID", "KOLIBRI_CONTAINER"):
            r = self.reasons("http://127.0.0.1:56462", environ={key: "kid-kolibri-demo"})
            self.assertTrue(any(key in x for x in r), (key, r))

    def test_refuses_docker_container_publishing_the_port(self):
        r = self.reasons("http://127.0.0.1:56462", docker_names=["kid-kolibri-demo-kolibri-1"])
        self.assertTrue(any("docker container" in x for x in r), r)

    def test_case_insensitive_name(self):
        r = self.reasons("http://127.0.0.1:56462", container="Kid-Kolibri-Demo")
        self.assertTrue(r)


class Guard(unittest.TestCase):
    def test_exits_nonzero_with_clear_message(self):
        err = io.StringIO()
        with mock.patch.object(sys, "stderr", err):
            with self.assertRaises(SystemExit) as e:
                cc.guard_live_demo("http://127.0.0.1:18090", environ={}, docker_names=[])
        self.assertEqual(e.exception.code, 2)
        msg = err.getvalue()
        self.assertIn("REFUSED", msg)
        self.assertIn("kid-kolibri-demo", msg)
        self.assertIn("18090", msg)
        self.assertIn(cc.OVERRIDE_ENV, msg)

    def test_main_refuses_before_any_login(self):
        err = io.StringIO()
        with mock.patch.object(sys, "stderr", err):
            with mock.patch.object(cc.sc, "Api") as api:
                with self.assertRaises(SystemExit) as e:
                    cc.main(["--url", "http://127.0.0.1:18091"])
        self.assertEqual(e.exception.code, 2)
        api.assert_not_called()
        self.assertIn("REFUSED", err.getvalue())

    def test_main_refuses_container_flag(self):
        err = io.StringIO()
        with mock.patch.object(sys, "stderr", err):
            with mock.patch.object(cc.sc, "Api") as api:
                with self.assertRaises(SystemExit) as e:
                    cc.main(["--url", "http://127.0.0.1:56462", "--container", "kid-kolibri-demo"])
        self.assertEqual(e.exception.code, 2)
        api.assert_not_called()

    def test_override_env_allows_the_check_to_proceed(self):
        cc.guard_live_demo("http://127.0.0.1:18090",
                           environ={cc.OVERRIDE_ENV: "1"}, docker_names=[])
        # non-1 values do not override
        with mock.patch.object(sys, "stderr", io.StringIO()):
            with self.assertRaises(SystemExit):
                cc.guard_live_demo("http://127.0.0.1:18090",
                                   environ={cc.OVERRIDE_ENV: "yes"}, docker_names=[])

    def test_main_on_throwaway_port_reaches_api(self):
        # Guard passes; Api() is constructed (and then login fails, which is fine).
        class Boom(Exception):
            pass

        def boom(*a, **k):
            raise Boom("api reached")

        with mock.patch.object(cc.sc, "Api", side_effect=boom):
            with self.assertRaises(Boom):
                cc.main(["--url", "http://127.0.0.1:56462"])


if __name__ == "__main__":
    unittest.main()
