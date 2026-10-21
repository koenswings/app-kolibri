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
"""
import argparse
import io
import json
import sys
import zipfile

sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__file__), "..", "demo"))
import seed_classwork as sc  # noqa: E402

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
    s = api.call("POST", "/api/logger/trackprogress/", dict(node_id=node["id"]))
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
    a = ap.parse_args(argv)

    L = sc.Api(a.url)
    fid, me = sc.login(L, a.learner, "")
    ok(me["kind"] == ["learner"], "%s signs in with username only" % a.learner)
    rooms = [c for c in L.get("/learn/api/learnerclassroom/") if c["name"] == a.klass]
    ok(len(rooms) == 1, "%s is in %s" % (a.learner, a.klass))
    asg = rooms[0]["assignments"]
    quizzes = [e for e in asg["exams"] if e["title"] == sc.QUIZ_TITLE]
    ok(len(quizzes) == 1 and quizzes[0]["active"], "learner sees active quiz %r" % sc.QUIZ_TITLE)
    lessons = asg["lessons"]
    ok(len(lessons) >= 1 and all(l["is_active"] for l in lessons),
       "learner sees %d active lesson(s): %s" % (len(lessons), ", ".join(l["title"] for l in lessons)))

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
    srcs = full["question_sources"]
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
    print(json.dumps(dict(result="pass", checks=len(CHECKS), quiz=exams[0]["id"], classroom=cid)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
