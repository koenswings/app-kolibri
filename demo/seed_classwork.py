#!/usr/bin/env python3
"""Seed the IDEA demo class work (lessons + quiz) through Kolibri's own REST API.

Runs against a RUNNING demo Kolibri, signed in as the class coach teacher1, so
it does exactly what a teacher does in Coach > Plan (no `kolibri manage shell`,
no database writes from outside Kolibri). Python 3 stdlib only.

Creates in class "Grade 5" of IDEA Demo School:
  * one lesson per channel on the device ("<channel> lesson"): every available
    resource of the channel, in channel order, active (visible to Grade 5);
  * one quiz "Grade 5 Practice Quiz": the questions of every exercise in the
    channels (in channel order, at most --max-questions), assigned to Grade 5,
    fixed order, and started (active), so learners see it under Classes > Grade 5.

Idempotent: an existing lesson/quiz with the same title in Grade 5 is updated
(resources / active) instead of duplicated. A quiz that learners already
answered keeps its questions (Kolibri forbids changing them); it is only made
active again.

Usage: seed_classwork.py --url http://127.0.0.1:PORT [--user teacher1]
         [--password teacher1911!] [--class "Grade 5"] [--no-lessons] [--dry-run]
Prints one JSON line at the end: {"result": "ok", "lessons": [...], "quiz": {...}}.
"""
import argparse
import http.cookiejar
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

FACILITY = "IDEA Demo School"
QUIZ_TITLE = "Grade 5 Practice Quiz"


class Api(object):
    def __init__(self, base):
        self.base = base.rstrip("/")
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def _csrf(self):
        for c in self.jar:
            if c.name.endswith("csrftoken"):  # 0.15.5: kolibri_csrftoken
                return c.value
        return ""

    def call(self, method, path, body=None, query=None):
        url = self.base + path + ("?" + urllib.parse.urlencode(query) if query else "")
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json")
        req.add_header("Referer", self.base + "/")
        if method != "GET":
            req.add_header("X-CSRFToken", self._csrf())
        try:
            with self.op.open(req, timeout=60) as r:
                raw = r.read()
        except urllib.error.HTTPError as e:
            raise SystemExit("ERROR %s %s -> HTTP %s: %s" % (method, path, e.code, e.read()[:500].decode("utf-8", "replace")))
        return json.loads(raw) if raw else None

    def get(self, path, **q):
        r = self.call("GET", path, query=q or None)
        return r["results"] if isinstance(r, dict) and "results" in r else r


def login(api, user, password):
    fac = [f for f in api.get("/api/public/v1/facility/") if f["name"] == FACILITY]
    if len(fac) != 1:
        raise SystemExit("ERROR: expected one facility %r, found %d" % (FACILITY, len(fac)))
    fid = fac[0]["id"]
    me = api.call("POST", "/api/auth/session/", dict(username=user, password=password, facility=fid))
    if me.get("username") != user:
        raise SystemExit("ERROR: could not sign in as %s" % user)
    return fid, me


def tree(api, channel):
    """Available non-topic nodes of a channel in channel (lft) order."""
    nodes = api.get("/api/content/contentnode/", channel_id=channel["id"])
    if isinstance(nodes, dict):
        nodes = nodes.get("results", [])
    nodes = [n for n in nodes if n["kind"] != "topic" and n.get("available", True)]
    return sorted(nodes, key=lambda n: (n.get("lft") or 0, n["title"]))


def upsert_lesson(api, cid, me, title, resources, dry):
    want = dict(title=title, collection=cid, description="IDEA demo lesson", is_active=True,
                resources=[dict(contentnode_id=n["id"], content_id=n["content_id"], channel_id=n["channel_id"])
                           for n in resources],
                lesson_assignments=[cid], created_by=me["user_id"])
    old = [l for l in api.get("/api/lessons/lesson/", collection=cid) if l["title"] == title]
    if dry:
        return dict(title=title, resources=len(resources), action="dry-run")
    if old:
        api.call("PATCH", "/api/lessons/lesson/%s/" % old[0]["id"],
                 dict(resources=want["resources"], is_active=True, lesson_assignments=[cid]))
        return dict(id=old[0]["id"], title=title, resources=len(resources), action="updated")
    r = api.call("POST", "/api/lessons/lesson/", want)
    return dict(id=r["id"], title=title, resources=len(resources), action="created")


def quiz_sources(exercises, limit):
    out = []
    for n in exercises:
        meta = n.get("assessmentmetadata") or {}
        for i, item in enumerate(meta.get("assessment_item_ids") or [], 1):
            if len(out) >= limit:
                return out
            out.append(dict(exercise_id=n["id"], question_id=item, title=n["title"], counter_in_exercise=i))
    return out


def upsert_quiz(api, cid, me, sources, dry):
    if not sources:
        raise SystemExit("ERROR: no exercises with questions found on this device; build the demo channels with exercises first")
    old = [e for e in api.get("/api/exams/exam/", collection=cid) if e["title"] == QUIZ_TITLE]
    if dry:
        return dict(title=QUIZ_TITLE, questions=len(sources), action="dry-run")
    if old:
        e = old[0]
        patch = dict(active=True, archive=False, assignments=[cid])
        if [ (q["exercise_id"], q.get("question_id")) for q in e["question_sources"] ] != \
           [ (q["exercise_id"], q["question_id"]) for q in sources ]:
            patch.update(question_sources=sources, question_count=len(sources))
        try:
            api.call("PATCH", "/api/exams/exam/%s/" % e["id"], patch)
        except SystemExit:
            if "question_sources" not in patch:
                raise
            # learners already answered: Kolibri refuses to change questions; keep them
            patch.pop("question_sources"); patch.pop("question_count")
            api.call("PATCH", "/api/exams/exam/%s/" % e["id"], patch)
        return dict(id=e["id"], title=QUIZ_TITLE, questions=len(sources), action="updated")
    r = api.call("POST", "/api/exams/exam/", dict(
        title=QUIZ_TITLE, collection=cid, assignments=[cid], question_sources=sources,
        question_count=len(sources), seed=2026, learners_see_fixed_order=True,
        active=False, archive=False, date_archived=None, date_activated=None, creator=me["user_id"]))
    # start it the way Coach does ("Start quiz" = PATCH active)
    api.call("PATCH", "/api/exams/exam/%s/" % r["id"], dict(active=True))
    return dict(id=r["id"], title=QUIZ_TITLE, questions=len(sources), action="created")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", required=True, help="Kolibri base URL, e.g. http://127.0.0.1:18320")
    ap.add_argument("--user", default="teacher1")
    ap.add_argument("--password", default="teacher1911!")
    ap.add_argument("--class", dest="klass", default="Grade 5")
    ap.add_argument("--max-questions", type=int, default=10)
    ap.add_argument("--no-lessons", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    api = Api(a.url)
    fid, me = login(api, a.user, a.password)
    cls = [c for c in api.get("/api/auth/classroom/", parent=fid) if c["name"] == a.klass]
    if len(cls) != 1:
        raise SystemExit("ERROR: expected one class %r in %s, found %d" % (a.klass, FACILITY, len(cls)))
    cid = cls[0]["id"]
    channels = sorted(api.get("/api/content/channel/", available="true"), key=lambda c: c["name"])
    lessons, exercises = [], []
    for ch in channels:
        res = tree(api, ch)
        exercises += [n for n in res if n["kind"] == "exercise"]
        if res and not a.no_lessons:
            lessons.append(upsert_lesson(api, cid, me, "%s lesson" % ch["name"], res, a.dry_run))
    quiz = upsert_quiz(api, cid, me, quiz_sources(exercises, a.max_questions), a.dry_run)
    print(json.dumps(dict(result="ok", classroom=cid, lessons=lessons, quiz=quiz,
                          exercises=len(exercises))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
