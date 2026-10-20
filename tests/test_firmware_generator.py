"""Tests for tools/generate_3d_firmware.py: asset dimensions, palette encoding, font coverage,
generated firmware syntax and host<->firmware bubble-layout parity."""

import ast
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import generate_3d_firmware as gen  # noqa: E402
import host_companion as hc  # noqa: E402

_SOURCE = None


def firmware_source() -> str:
    global _SOURCE
    if _SOURCE is None:
        _SOURCE = gen.generate_firmware_source()
    return _SOURCE


def load_firmware_function(name: str):
    """Extracts a pure top-level function from the generated firmware and execs it."""
    tree = ast.parse(firmware_source())
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            ns = {}
            exec(compile(ast.Module(body=[node], type_ignores=[]), "<fw>", "exec"), ns)
            return ns[name]
    raise KeyError(name)


class PaletteTests(unittest.TestCase):
    def test_palette_has_64_rgb_entries(self):
        self.assertEqual(len(gen.PALETTE), 64)
        for c in gen.PALETTE:
            self.assertEqual(len(c), 3)
            self.assertTrue(all(0 <= v <= 255 for v in c))

    def test_alpha_encoding_is_safe(self):
        self.assertGreaterEqual(len(gen.ALPHA), 64)  # one symbol per palette index
        self.assertEqual(len(set(gen.ALPHA)), len(gen.ALPHA))
        self.assertEqual(gen.ALPHA[0], ".")
        for bad in ('"', "\\", "'"):
            self.assertNotIn(bad, gen.ALPHA)


class AssetTests(unittest.TestCase):
    def _check(self, rows, w, h):
        self.assertEqual(len(rows), h)
        for r in rows:
            self.assertEqual(len(r), w)
            self.assertTrue(set(r) <= set(gen.ALPHA))

    def test_eye_tiles(self):
        for mode in ("NORMAL", "HALF", "BLINK", "HAPPY", "THINK", "SLEEP", "PARTY"):
            self._check(gen.render_3d_eyes_tile(mode), 32, 20)

    def test_prop_tiles(self):
        self._check(gen.render_3d_coffee_prop(0), 32, 24)
        self._check(gen.render_3d_laptop_prop(1), 32, 24)
        self._check(gen.render_3d_bulb_prop(0), 32, 24)

    def test_bot_pose_fills_screen_height(self):
        rows = gen.raymarch_grok_pose(66, 75, "STAND")
        self._check(rows, 66, 75)
        opaque = [i for i, r in enumerate(rows) if r.strip(".")]
        self.assertGreaterEqual(opaque[-1] - opaque[0], 60)


class FontTests(unittest.TestCase):
    def test_glyphs_are_6x8(self):
        for ch, g in gen.FONT_6X8_BOLD.items():
            self.assertEqual(len(g), 8, ch)
            for row in g:
                self.assertEqual(len(row), 6, ch)
                self.assertTrue(set(row) <= {"0", "1"}, ch)

    def test_font_covers_host_allowed_charset(self):
        allowed = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!?.,+-/:%#><_ "
        for ch in allowed:
            self.assertIn(ch, gen.FONT_6X8_BOLD, ch)

    def test_default_phrases_render_and_fit(self):
        src = firmware_source()
        m = re.search(r"DEFAULT_PHRASES = \{(.*?)\n\}", src, re.DOTALL)
        phrases = re.findall(r'"([^"]+)"', m.group(1))
        split = load_firmware_function("split_callout_lines")
        for p in phrases:
            if p.isupper() and p in ("CODING", "COFFEE", "THINKING", "CHILL", "SLEEP", "OVERLOAD", "PARTY"):
                continue
            for ch in p:
                self.assertIn(ch, gen.FONT_6X8_BOLD, f"{p!r} uses unsupported {ch!r}")
            self.assertEqual(" ".join(split(p)), p, f"{p!r} is truncated in the bubble")


class FirmwareSourceTests(unittest.TestCase):
    def test_compiles(self):
        compile(firmware_source(), "code.py", "exec")

    def test_no_per_frame_math_import(self):
        # Animation uses the SIN_64 lookup table instead of math.sin per frame.
        self.assertNotIn("math.sin", firmware_source())

    def test_bubble_layout_parity_with_host(self):
        split = load_firmware_function("split_callout_lines")
        samples = ["DEEP WORK", "NEED COFFEE", "CURSOR AGAIN?", "TESTS RED?!", "PR MERGED!",
                   "2H IN VIM", "BACK FROM AFK", "WTF?!", "CPU ON FIRE", "READ THE DOCS"]
        for s in samples:
            clean = hc.sanitize_thought(s)
            host_lines = hc.layout_bubble_lines(clean)
            self.assertIsNotNone(host_lines, s)
            self.assertEqual(list(split(clean)), host_lines, s)


if __name__ == "__main__":
    unittest.main()
