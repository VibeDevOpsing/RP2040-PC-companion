"""Unit tests for the host daemon: thought sanitizing, bubble layout, protocol, timeline,
LLM JSON parsing, reflex classification and the background ThoughtEngine."""

import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import host_companion as hc  # noqa: E402


class BubbleLayoutTests(unittest.TestCase):
    def test_single_line_fits(self):
        self.assertEqual(hc.layout_bubble_lines("DEEP WORK"), ["DEEP WORK"])

    def test_wraps_to_two_lines(self):
        self.assertEqual(hc.layout_bubble_lines("NEED COFFEE"), ["NEED", "COFFEE"])

    def test_rejects_three_lines(self):
        self.assertIsNone(hc.layout_bubble_lines("ONE TWO THREE FOUR FIVE SIX"))

    def test_rejects_overlong_word(self):
        self.assertIsNone(hc.layout_bubble_lines("SUPERCALIFRAGILISTIC"))


class SanitizeThoughtTests(unittest.TestCase):
    def test_uppercases_and_strips_unsupported(self):
        self.assertEqual(hc.sanitize_thought("tests red?! 🔥"), "TESTS RED?!")

    def test_removes_apostrophes(self):
        self.assertEqual(hc.sanitize_thought("don't panic"), "DONT PANIC")

    def test_tilde_is_reserved_for_protocol(self):
        self.assertNotIn("~", hc.sanitize_thought("yt break~"))

    def test_drops_words_until_it_fits(self):
        out = hc.sanitize_thought("this is way too many words for the bubble")
        self.assertTrue(out)
        self.assertIsNotNone(hc.layout_bubble_lines(out))

    def test_non_string(self):
        self.assertEqual(hc.sanitize_thought(None), "")
        self.assertEqual(hc.sanitize_thought(42), "")

    def test_thoughts_list_dedup_and_limit(self):
        out = hc.sanitize_thoughts(["lgtm!", "LGTM!", "ship it", "pr merged", "gg"])
        self.assertEqual(out, ["LGTM!", "SHIP IT", "PR MERGED"])

    def test_thoughts_from_string(self):
        self.assertEqual(hc.sanitize_thoughts("a~b\nc"), ["A", "B", "C"])

    def test_thoughts_invalid_type(self):
        self.assertEqual(hc.sanitize_thoughts({"x": 1}), [])


class PacketTests(unittest.TestCase):
    def test_packet_format(self):
        pkt = hc.build_packet("CODING", "CYBER", ["lgtm!", "ship it"], "focused", "coding",
                              80, 12, "none", "code_matrix", 14)
        self.assertTrue(pkt.endswith("\n"))
        fields = dict(p.split(":", 1) for p in pkt.strip().split("|"))
        self.assertEqual(fields["STATE"], "CODING")
        self.assertEqual(fields["MSG"], "LGTM!~SHIP IT")
        self.assertEqual(fields["HOUR"], "14")

    def test_empty_thoughts_send_empty_msg(self):
        pkt = hc.build_packet("SLEEP", "INDIGO", [], "sleepy", "sleeping", 50, 3, "none", "zzz_dream", 2)
        self.assertIn("|MSG:|", pkt)

    def test_packet_never_contains_extra_separators(self):
        pkt = hc.build_packet("CODING", "CYBER", ["a|b:c"], "focused", "coding", 1, 1, "none", "x", 0)
        self.assertEqual(pkt.count("|"), 9)


class _FakeSerial:
    def __init__(self):
        self.writes = []
        self.is_open = True

    def write(self, data):
        self.writes.append(data)

    def flush(self):
        pass


class SendStateDedupeTests(unittest.TestCase):
    def setUp(self):
        self.board = hc.BoardSerial(port_override="fake")
        self.fake = _FakeSerial()
        self.board.ser = self.fake

    def _send(self, **kw):
        base = dict(mood="focused", act="coding", nrg=80, cpu=10, evt="none",
                    poster="code_matrix", state="CODING", theme="CYBER", thoughts=["LGTM!"])
        base.update(kw)
        return self.board.send_state(**base)

    def test_cpu_jitter_does_not_resend(self):
        self._send(cpu=10)
        self._send(cpu=27)
        self.assertEqual(len(self.fake.writes), 1)

    def test_semantic_change_resends(self):
        self._send()
        self._send(thoughts=["SHIP IT"])
        self.assertEqual(len(self.fake.writes), 2)

    def test_heartbeat_resends(self):
        self._send()
        self.board.last_send_ts -= hc.SERIAL_HEARTBEAT_SEC + 1
        self._send()
        self.assertEqual(len(self.fake.writes), 2)


class TimelineTests(unittest.TestCase):
    def test_switch_detection_and_summary(self):
        tl = hc.ActivityTimeline()
        t0 = 1000.0
        self.assertTrue(tl.update("Cursor", "main.py", t0))
        self.assertFalse(tl.update("Cursor", "utils.py", t0 + 10))
        self.assertTrue(tl.update("Safari", "Docs", t0 + 120))
        self.assertFalse(tl.update("Unknown", "", t0 + 130))
        s = tl.summary(t0 + 180)
        self.assertIn("3m ago: Cursor — utils.py", s)
        self.assertIn("1m ago: Safari — Docs", s)
        self.assertAlmostEqual(tl.dwell_minutes(t0 + 180), 1.0)


class ParseLlmJsonTests(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(hc.parse_llm_json('{"a": 1}'), {"a": 1})

    def test_think_block_and_fence(self):
        txt = '<think>{"no": 1}</think>```json\n{"thoughts": ["X", "Y"]}\n```'
        self.assertEqual(hc.parse_llm_json(txt), {"thoughts": ["X", "Y"]})

    def test_embedded_with_array(self):
        txt = 'Sure! {"state": "CODING", "thoughts": ["A", "B"]} hope that helps'
        self.assertEqual(hc.parse_llm_json(txt)["thoughts"], ["A", "B"])

    def test_reasoning_fallback(self):
        self.assertEqual(hc.parse_llm_json("", '{"k": 2}'), {"k": 2})

    def test_garbage(self):
        self.assertIsNone(hc.parse_llm_json("no json here"))


class ReflexTests(unittest.TestCase):
    def test_idle_sleep(self):
        self.assertEqual(hc.classify_reflex("Cursor", "x", 999, 10, 80)[3], "SLEEP")

    def test_cpu_overload(self):
        self.assertEqual(hc.classify_reflex("Cursor", "x", 0, 95, 80)[3], "OVERLOAD")

    def test_debug_keywords(self):
        self.assertEqual(hc.classify_reflex("Terminal", "Traceback (most recent)", 0, 10, 80)[3], "OVERLOAD")

    def test_music_chill(self):
        self.assertEqual(hc.classify_reflex("Spotify", "", 0, 10, 80)[3], "CHILL")


class _FakeBrain:
    def __init__(self):
        self.calls = 0
        self.called = threading.Event()

    def analyze_context(self, **ctx):
        self.calls += 1
        self.called.set()
        return {"state": "CODING", "thoughts": [f"CALL {self.calls}"]}


class ThoughtEngineTests(unittest.TestCase):
    def test_trigger_produces_result_without_blocking(self):
        brain = _FakeBrain()
        eng = hc.ThoughtEngine(brain, interval=60.0, min_gap=0.0).start()
        try:
            t0 = time.time()
            eng.update_context({"app_name": "X"})
            eng.trigger()
            self.assertLess(time.time() - t0, 0.05)  # trigger is non-blocking
            self.assertTrue(brain.called.wait(2.0))
            deadline = time.time() + 2.0
            res = None
            while res is None and time.time() < deadline:
                res = eng.poll()
                time.sleep(0.01)
            self.assertIsNotNone(res)
            self.assertEqual(res["thoughts"], ["CALL 1"])
            self.assertIsNone(eng.poll())  # result is consumed once
        finally:
            eng.stop()

    def test_no_context_no_call(self):
        brain = _FakeBrain()
        eng = hc.ThoughtEngine(brain, interval=60.0, min_gap=0.0).start()
        try:
            eng.trigger()
            self.assertFalse(brain.called.wait(0.3))
        finally:
            eng.stop()


if __name__ == "__main__":
    unittest.main()
