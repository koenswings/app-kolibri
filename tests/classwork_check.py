#!/usr/bin/env python3
"""Check the seeded demo class work end to end over Kolibri's HTTP API (stdlib only).

As learner1 (username only): sees the lessons and the quiz in Classes > Grade 5,
the exercises are servable (perseus file with exercise.json + one JSON item per
question, what Kolibri's perseus viewer loads), does an exercise (answers every
question right until mastery) and does the quiz. Then as teacher1: Coach class
summary shows learner1's exercise and quiz as completed.

Usage: classwork_check.py --url http://127.0.0.1:PORT [--learner learner1]
Prints PASS lines and a final JSON line; exit 1 on the first failure.
Only for a throwaway/test demo instance: it records learner progress.
Refuses the live idea03 demo (instance or container name containing
kid-kolibri-demo, or ports 18090/18091). Override only with
KOLIBRI_CHECK_I_KNOW_THIS_IS_NOT_THE_DEMO=1.
"""
import argparse
import io
import json
import os
import subprocess
import sys
import zipfile
from urllib.parse import urlparse

sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__file__), "..", "demo"))
import seed_classwork as sc  # noqa: E402

LIVE_DEMO_NAME = "kid-kolibri-demo"
LIVE_DEMO_PORTS = frozenset((18090, 18091))
OVERRIDE_ENV = "KOLIBRI_CHECK_I_KNOW_THIS_IS_NOT_THE_DEMO"


def url_port(url):
    p = urlparse(url)
    if p.port:
        return p.port
    if p.scheme == "https":
        return 443
    if p.scheme == "http":
        return 80
    return None


def _has_live_demo_name(value):
    return bool(value) and LIVE_DEMO_NAME in value.lower()


def names_from_docker_ps(output, port):
    """Container names from `docker ps --format '{{.Names}}\t{{.Ports}}'` that publish port."""
    if not port or not output:
        return []
    token = ":%s->" % port
    names = []
    for line in output.splitlines():
        name, sep, ports = line.partition("\t")
        if sep and token in ports:
            names.append(name)
    return names


def docker_names_publishing(url):
    """Best-effort: names of running containers that publish this URL's port."""
    port = url_port(url)
    if not port:
        return []
    try:
        out = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}\t{{.Ports}}"],
            capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if out.returncode != 0:
        return []
    return names_from_docker_ps(out.stdout, port)


def live_demo_reasons(url, container=None, environ=None, docker_names=None):
    """Why this target looks like the live kid-kolibri-demo, or an empty list.

    Facility name is not used: throwaway test instances are also seeded as
    'IDEA Demo School'. The live demo is identified by instance name and ports.
    """
    env = os.environ if environ is None else environ
    reasons = []
    port = url_port(url)
    if port in LIVE_DEMO_PORTS:
        reasons.append("port %s is reserved for the live %s instance" % (port, LIVE_DEMO_NAME))
    p = urlparse(url)
    if _has_live_demo_name(p.hostname) or _has_live_demo_name(url):
        reasons.append("URL %r contains %s" % (url, LIVE_DEMO_NAME))
    names = []
    if container:
        names.append(("container", container))
    for key in ("COMPOSE_PROJECT_NAME", "IDEA_INSTANCE_ID", "KOLIBRI_CONTAINER"):
        val = env.get(key)
        if val:
            names.append((key, val))
    if docker_names is None:
        docker_names = docker_names_publishing(url)
    for n in docker_names:
        names.append(("docker container", n))
    seen = set()
    for label, value in names:
        if value in seen:
            continue
        seen.add(value)
        if _has_live_demo_name(value):
            reasons.append("%s %r is or contains %s" % (label, value, LIVE_DEMO_NAME))
    return reasons


def guard_live_demo(url, container=None, environ=None, docker_names=None):
    """Exit 2 if the target is the live demo, unless the override env is 1."""
    env = os.environ if environ is None else environ
    if env.get(OVERRIDE_ENV) == "1":
        return
    reasons = live_demo_reasons(url, container=container, environ=env,
                                docker_names=docker_names)
    if not reasons:
        return
    sys.stderr.write(
        "REFUSED: classwork_check.py records learner progress and must not run "
        "against the live demo %s.\n" % LIVE_DEMO_NAME)
    for r in reasons:
        sys.stderr.write("  - %s\n" % r)
    sys.stderr.write(
        "Only use a throwaway test instance. If you are sure this is not the "
        "live demo, set %s=1.\n" % OVERRIDE_ENV)
    raise SystemExit(2)


CHECKS = []


def ok(cond, msg):
    if not cond:
        print("FAIL: " + msg)
        sys.exit(1)
    CHECKS.append(msg)
    print("PASS: " + msg)


def raw(api, path):
    with api.op.open(api.base + path, timeout=60) as r:
        return r.read()


def mastered(mm, answers):
    if mm["type"] == "do_all":
        return False  # do_all: all questions -> counted by caller
    last = answers[-mm["n"]:]
    return sum(last) >= mm["m"]


def do_exercise(api, node):
    meta = node["assessmentmetadata"]
    items = meta["assessment_item_ids"]
    mm = meta["mastery_model"]
    if isinstance(mm, str):
        mm = json.loads(mm)
    s = api.call("POST", "/api/logger/trackprogress/", dict(  # 0.19.5 needs kind/content/channel/mastery
        node_id=node["id"], content_id=node["content_id"], channel_id=node["channel_id"],
        kind="exercise", mastery_model=mm))
    ok(s.get("mastery_criterion", {}).get("type") == mm["type"],
       "exercise %r: session started with mastery %s" % (node["title"], mm))
    answers, out = [], None
    need = len(items) if mm["type"] == "do_all" else mm["n"]
    for i in range(need):
        item = items[i % len(items)]
        answers.append(1)
        done = (len(answers) >= need) if mm["type"] == "do_all" else mastered(mm, answers)
        out = api.call("PUT", "/api/logger/trackprogress/%s/" % s["session_id"], dict(
            progress=1.0 if done else min(0.99, len(answers) / float(need)), time_spent_delta=5,
            interactions=[dict(item=item, correct=1, complete=True, time_spent=5,
                               answer={"answer": "ok"}, simple_answer="ok")]))
        if done:
            break
    ok(out and out.get("complete") is True, "exercise %r: learner answered, progress recorded, complete" % node["title"])


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--learner", default="learner1")
    ap.add_argument("--class", dest="klass", default="Grade 5")
    ap.add_argument("--container", default=None,
                    help="optional container or instance name, used by the live-demo guard")
    a = ap.parse_args(argv)
    guard_live_demo(a.url, container=a.container)

    L = sc.Api(a.url)
    fid, me = sc.login(L, a.learner, "")
    ok(me["kind"] == ["learner"], "%s signs in with username only" % a.learner)
    rooms = [c for c in L.get("/learn/api/learnerclassroom/") if c["name"] == a.klass]
    ok(len(rooms) == 1, "%s is in %s" % (a.learner, a.klass))
    asg = rooms[0].get("assignments") or rooms[0]  # 0.15.5: under "assignments"; 0.19.5: top level
    quizzes = [e for e in asg["exams"] if e["title"] == sc.QUIZ_TITLE]
    ok(len(quizzes) == 1 and quizzes[0]["active"], "learner sees active quiz %r" % sc.QUIZ_TITLE)
    lessons = asg["lessons"]
    titles = [l["title"] for l in lessons]
    ok(len(lessons) == 3 and all(l.get("is_active", l.get("active")) for l in lessons),
       "learner sees 3 active lessons: %s" % ", ".join(titles))
    ok(not any(sc.is_khan_lesson(t) for t in titles), "learner does not see a Khan Academy lesson")

    exercises = []
    for ch in [c for c in L.get("/api/content/channel/", available="true") if c["name"] in sc.DEMO_CHANNELS]:
        exercises += [n for n in sc.tree(L, ch) if n["kind"] == "exercise"]
    ok(exercises, "%d exercise(s) on the device" % len(exercises))
    for n in exercises:
        node = L.get("/api/content/contentnode/%s/" % n["id"])
        f = [x for x in node["files"] if x["preset"] == "exercise"]
        ok(len(f) == 1 and f[0]["extension"] == "perseus" and f[0]["available"],
           "exercise %r has an available .perseus file" % n["title"])
        z = zipfile.ZipFile(io.BytesIO(raw(L, f[0]["storage_url"])))
        ids = node["assessmentmetadata"]["assessment_item_ids"]
        widgets = []
        for i in ids:
            item = json.loads(z.read("%s.json" % i))
            widgets += [w["type"] for w in item["question"]["widgets"].values()]
            ok("[[\u2603" in item["question"]["content"], "item %s of %r is a Perseus question" % (i[:8], n["title"]))
        ok(set(widgets) <= {"radio", "numeric-input"}, "widgets of %r: %s" % (n["title"], sorted(set(widgets))))
    do_exercise(L, L.get("/api/content/contentnode/%s/" % exercises[0]["id"]))

    T = sc.Api(a.url)
    fid, tme = sc.login(T, "teacher1", "teacher1911!")
    q = quizzes[0]
    try:  # the learner's quiz page reads the same exam object
        full = L.get("/api/exams/exam/%s/" % q["id"])
    except SystemExit:
        full = T.get("/api/exams/exam/%s/" % q["id"])
    s = L.call("POST", "/api/logger/trackprogress/", dict(quiz_id=q["id"]))
    srcs = sc.flatten_questions(full["question_sources"])
    ok(srcs, "quiz has questions after flatten (V3 sections or V2 list)")
    for k, src in enumerate(srcs, 1):
        out = L.call("PUT", "/api/logger/trackprogress/%s/" % s["session_id"], dict(
            progress=k / float(len(srcs)), time_spent_delta=5,
            interactions=[dict(item="%s:%s" % (src["exercise_id"], src["question_id"]), correct=1,
                               complete=True, time_spent=5, answer={"answer": "ok"}, simple_answer="ok")]))
    ok(out.get("complete") is True, "learner submitted all %d quiz answers" % len(srcs))

    cid = rooms[0]["id"]
    summ = T.get("/coach/api/classsummary/%s/" % cid)
    lid = me["user_id"]
    exams = [e for e in summ["exams"] if e["title"] == sc.QUIZ_TITLE]
    ok(len(exams) == 1 and exams[0]["active"] and cid in exams[0]["assignments"],
       "teacher1: quiz exists, active, assigned to %s" % a.klass)
    est = [x for x in summ["exam_learner_status"] if x["learner_id"] == lid and x["exam_id"] == exams[0]["id"]]
    ok(est and est[0]["status"] == "Completed" and est[0]["num_correct"] == len(srcs),
       "teacher1 sees %s's quiz: %s, %s/%d correct" % (a.learner, est and est[0]["status"],
                                                     est and est[0]["num_correct"], len(srcs)))
    cst = [x for x in summ["content_learner_status"] if x["learner_id"] == lid
           and x["content_id"] == exercises[0]["content_id"]]
    ok(cst and cst[0]["status"] == "Completed",
       "teacher1 sees %s's exercise %r: %s" % (a.learner, exercises[0]["title"], cst and cst[0]["status"]))
    summ_lessons = summ.get("lessons") or []
    ok(len(summ_lessons) == 3, "Coach class summary has 3 lessons (not a hidden 4th): %s"
       % [l["title"] for l in summ_lessons])
    ok(not any(sc.is_khan_lesson(l.get("title")) for l in summ_lessons),
       "Coach class summary has no Khan Academy lesson")

    # Same query as 0.19.5 LearnerClassEnrollmentPage (member_of facility,
    # exclude_member_of + exclude_coach_for the class; no user_type=learner filter).
    # Signed in as admin, the user who opens Facility > Classes > Enroll learners.
    A = sc.Api(a.url)
    sc.login(A, "admin", "admin911!")
    enroll = A.get("/api/auth/facilityuser/", member_of=fid, exclude_member_of=cid, exclude_coach_for=cid)
    enroll_names = sorted(u["username"] for u in enroll)
    ok("admin" not in enroll_names, "admin is not on the Enroll learners list (%s)" % enroll_names)
    ok("learner4" in enroll_names, "learner4 is on the Enroll learners list (%s)" % enroll_names)

    print(json.dumps(dict(result="pass", checks=len(CHECKS), quiz=exams[0]["id"], classroom=cid)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
