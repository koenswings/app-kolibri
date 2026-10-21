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


class Tree(unittest.TestCase):
    def test_channel_order_and_no_topics(self):
        class FakeApi(object):
            def get(self, path, **q):
                return [dict(id="t", kind="topic", lft=1, title="T"), dict(id="2", kind="video", lft=5, title="V"),
                        dict(id="1", kind="exercise", lft=3, title="E"),
                        dict(id="3", kind="document", lft=7, title="D", available=False)]
        self.assertEqual([n["id"] for n in sc.tree(FakeApi(), dict(id="c"))], ["1", "2"])


if __name__ == "__main__":
    unittest.main()
