"""Unit tests for demo/seed_classwork.py (no Kolibri needed)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "demo"))
import seed_classwork as sc  # noqa: E402


def ex(nid, title, items):
    return dict(id=nid, title=title, kind="exercise", assessmentmetadata=dict(assessment_item_ids=items))


class QuizSources(unittest.TestCase):
    def test_v2_sources_in_order_with_counter(self):
        s = sc.quiz_sources([ex("a" * 32, "Fractions", ["1" * 32, "2" * 32]), ex("b" * 32, "Reading", ["3" * 32])], 10)
        self.assertEqual([(q["exercise_id"][0], q["question_id"][0], q["counter_in_exercise"]) for q in s],
                         [("a", "1", 1), ("a", "2", 2), ("b", "3", 1)])
        self.assertEqual(s[2]["title"], "Reading")

    def test_limit(self):
        s = sc.quiz_sources([ex("a" * 32, "A", ["%032x" % i for i in range(8)]), ex("b" * 32, "B", ["f" * 32])], 5)
        self.assertEqual(len(s), 5)
        self.assertTrue(all(q["exercise_id"] == "a" * 32 for q in s))

    def test_no_exercises_fails_clearly(self):
        with self.assertRaises(SystemExit) as e:
            sc.upsert_quiz(None, "c", {}, [], False)
        self.assertIn("no exercises", str(e.exception))


class QuizSections(unittest.TestCase):
    def test_wraps_v2_as_one_section(self):
        sources = sc.quiz_sources([ex("a" * 32, "Fractions", ["1" * 32, "2" * 32])], 10)
        sections = sc.quiz_sections(sources, fixed_order=True)
        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0]["section_title"], sc.QUIZ_SECTION_TITLE)
        self.assertTrue(sections[0]["learners_see_fixed_order"])
        self.assertEqual(sections[0]["questions"], sources)

    def test_flatten_v3_and_v2(self):
        q1 = dict(exercise_id="a" * 32, question_id="1" * 32, title="A", counter_in_exercise=1)
        q2 = dict(exercise_id="b" * 32, question_id="2" * 32, title="B", counter_in_exercise=1)
        self.assertEqual(sc.flatten_questions(sc.quiz_sections([q1, q2])), [q1, q2])
        self.assertEqual(sc.flatten_questions([q1, q2]), [q1, q2])
        self.assertEqual(sc.question_pairs(sc.quiz_sections([q1, q2])), [(q1["exercise_id"], q1["question_id"]),
                                                                        (q2["exercise_id"], q2["question_id"])])

    def test_is_v3_sections(self):
        q = dict(exercise_id="a" * 32, question_id="1" * 32, title="A", counter_in_exercise=1)
        self.assertTrue(sc.is_v3_sections(sc.quiz_sections([q])))
        self.assertFalse(sc.is_v3_sections([q]))
        self.assertFalse(sc.is_v3_sections([]))


class DraftDetection(unittest.TestCase):
    def test_draft_flag_and_integer_pk(self):
        self.assertTrue(sc.is_draft_exam(dict(id=7, draft=True, title=sc.QUIZ_TITLE)))
        self.assertFalse(sc.is_draft_exam(dict(id="a" * 32, draft=False, title=sc.QUIZ_TITLE)))
        self.assertTrue(sc.is_draft_exam(dict(id="12")))  # leftover draft without the flag
        self.assertFalse(sc.is_draft_exam(dict(id="a" * 32)))


class LessonPayload(unittest.TestCase):
    def test_sends_019_and_015_field_names(self):
        node = dict(id="n" * 32, content_id="c" * 32, channel_id="h" * 32)
        p = sc.lesson_payload("classid", dict(user_id="u"), "Maths lesson", [node])
        self.assertTrue(p["active"] and p["is_active"])
        self.assertEqual(p["assignments"], ["classid"])
        self.assertEqual(p["lesson_assignments"], ["classid"])
        self.assertEqual(p["resources"][0]["contentnode_id"], "n" * 32)


class Tree(unittest.TestCase):
    def test_channel_order_and_no_topics(self):
        class FakeApi(object):
            def get(self, path, **q):
                return [dict(id="t", kind="topic", lft=1, title="T"), dict(id="2", kind="video", lft=5, title="V"),
                        dict(id="1", kind="exercise", lft=3, title="E"),
                        dict(id="3", kind="document", lft=7, title="D", available=False)]
        self.assertEqual([n["id"] for n in sc.tree(FakeApi(), dict(id="c"))], ["1", "2"])


class UpsertQuizRequests(unittest.TestCase):
    """The 0.19.5 create/publish path must not PATCH active=True on a DraftExam."""

    def _sources(self):
        return sc.quiz_sources([ex("a" * 32, "Fractions", ["1" * 32, "2" * 32])], 10)

    def test_create_posts_published_v3_quiz(self):
        calls = []

        class FakeApi(object):
            def get(self, path, **q):
                return []

            def call(self, method, path, body=None, query=None):
                calls.append((method, path, body))
                return dict(id="e" * 32, draft=False, active=True, title=sc.QUIZ_TITLE)

        out = sc.upsert_quiz(FakeApi(), "classid", dict(user_id="u"), self._sources(), False)
        self.assertEqual(out["action"], "created")
        self.assertEqual(len(calls), 1)
        method, path, body = calls[0]
        self.assertEqual((method, path), ("POST", "/api/exams/exam/"))
        self.assertEqual(body["draft"], False)
        self.assertTrue(body["active"])
        self.assertEqual(body["assignments"], ["classid"])
        self.assertIn("questions", body["question_sources"][0])
        self.assertEqual(len(body["question_sources"][0]["questions"]), 2)

    def test_leftover_draft_is_rewritten_then_published(self):
        calls = []
        # V2 flats stored as if they were sections: the 0.19.5 bug leftover.
        leftover = [dict(exercise_id="a" * 32, question_id="1" * 32, title="Fractions", counter_in_exercise=1),
                    dict(exercise_id="a" * 32, question_id="2" * 32, title="Fractions", counter_in_exercise=2)]

        class FakeApi(object):
            def get(self, path, **q):
                return [dict(id=7, title=sc.QUIZ_TITLE, draft=True, question_sources=leftover, active=False)]

            def call(self, method, path, body=None, query=None):
                calls.append((method, path, body))
                if body and body.get("draft") is False:
                    return dict(id="e" * 32, draft=False, active=True, title=sc.QUIZ_TITLE)
                return dict(id=7, draft=True, title=sc.QUIZ_TITLE)

        out = sc.upsert_quiz(FakeApi(), "classid", dict(user_id="u"), self._sources(), False)
        self.assertEqual(out["action"], "updated")
        self.assertEqual(out["id"], "e" * 32)
        self.assertEqual([c[0] for c in calls], ["PATCH", "PATCH"])
        self.assertIn("questions", calls[0][2]["question_sources"][0])
        self.assertEqual(calls[1][2], dict(draft=False, active=True, archive=False, assignments=["classid"]))
        # Never a lone active=True patch on the draft.
        self.assertFalse(any(c[2] == dict(active=True) for c in calls))

    def test_published_exam_is_only_reactivated(self):
        calls = []

        class FakeApi(object):
            def get(self, path, **q):
                return [dict(id="e" * 32, title=sc.QUIZ_TITLE, draft=False, active=False,
                             question_sources=sc.quiz_sections(self_sources), assignments=["classid"])]

            def call(self, method, path, body=None, query=None):
                calls.append((method, path, body))
                return dict(id="e" * 32, draft=False, active=True)

        self_sources = self._sources()
        out = sc.upsert_quiz(FakeApi(), "classid", dict(user_id="u"), self_sources, False)
        self.assertEqual(out["action"], "updated")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][2], dict(active=True, archive=False, assignments=["classid"]))
        self.assertNotIn("question_sources", calls[0][2])
        self.assertNotIn("draft", calls[0][2])


class ProgressPlan(unittest.TestCase):
    def test_exercise_answers_reach_mastery_after_one_wrong(self):
        self.assertEqual(sc.exercise_answers({"type": "m_of_n", "m": 4, "n": 5}, 6), [0, 1, 1, 1, 1])
        self.assertEqual(sc.exercise_answers({"type": "do_all"}, 4), [0, 1, 1, 1, 1])
        self.assertEqual(sc.exercise_answers({"type": "num_correct_in_a_row_3"}, 6), [0, 1, 1, 1])
        mm = sc.mastery_model(dict(assessmentmetadata=dict(mastery_model='{"type": "m_of_n", "m": 4, "n": 5}')))
        self.assertEqual(mm["m"], 4)

    def test_quiz_answers_seven_of_ten(self):
        a = sc.quiz_answers(10)
        self.assertEqual((len(a), sum(a)), (10, 7))

    def test_status_of(self):
        rows = [dict(learner_id="L", content_id="c", status="Completed"), dict(learner_id="M", content_id="c", status="Started")]
        self.assertEqual(sc.status_of(rows, "L", "content_id", "c"), "Completed")
        self.assertIsNone(sc.status_of(rows, "X", "content_id", "c"))


class SeedProgressIdempotent(unittest.TestCase):
    """A rerun writes nothing when Coach already shows the learner's items as Completed."""

    EX = dict(id="e" * 32, content_id="ec" * 16, channel_id="h" * 32, kind="exercise", title="Fractions practice",
              assessmentmetadata=dict(assessment_item_ids=["1" * 32], mastery_model={"type": "do_all"}))
    VID = dict(id="v" * 32, content_id="vc" * 16, channel_id="h" * 32, kind="video", title="Counting fruit")

    def summary(self, done):
        st = "Completed" if done else "Started"
        return dict(learners=[dict(id="L3", username="learner3")],
                    exams=[dict(id="q" * 32, title=sc.QUIZ_TITLE)],
                    content_learner_status=[dict(learner_id="L3", content_id=self.EX["content_id"], status=st),
                                            dict(learner_id="L3", content_id=self.VID["content_id"], status=st)],
                    exam_learner_status=[dict(learner_id="L3", exam_id="q" * 32, status=st)] if done else [])

    def test_rerun_writes_nothing(self):
        calls = []
        summ = self.summary(True)

        class FakeApi(object):
            def get(self, path, **q):
                return summ

            def call(self, method, path, body=None, query=None):
                calls.append((method, path))
                return {}

        out = sc.seed_progress(FakeApi(), "http://x", "classid", "learner3",
                               {"Maths lesson": dict(id="lessonid", title="Maths lesson")}, "q" * 32,
                               {"lessonid": [self.VID, self.EX]}, False)
        self.assertEqual(calls, [])
        self.assertEqual([i["action"] for i in out["items"]], ["unchanged", "unchanged", "unchanged"])
        self.assertEqual([i["title"] for i in out["items"]], ["Fractions practice", "Counting fruit", sc.QUIZ_TITLE])

    def test_learner_must_be_enrolled(self):
        class FakeApi(object):
            def get(self, path, **q):
                return dict(learners=[])
        with self.assertRaises(SystemExit) as e:
            sc.seed_progress(FakeApi(), "http://x", "c", "learner3", {}, "q", {}, False)
        self.assertIn("not enrolled", str(e.exception))


if __name__ == "__main__":
    unittest.main()
