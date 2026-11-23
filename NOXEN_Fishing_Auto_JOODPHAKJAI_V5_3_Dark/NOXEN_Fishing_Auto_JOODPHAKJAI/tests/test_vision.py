import unittest
import numpy as np

from core.vision import detect_charge, detect_control_bar, detect_fish_marker, detect_handle_center, detect_progress, detect_target_center, fisch_should_hold


class VisionTests(unittest.TestCase):
    def test_charge_reads_white_fill_below_green_cap(self):
        # Match the supplied UI: narrow green/yellow-green top and white fill below.
        frame = np.full((308, 118, 3), (28, 32, 25), dtype=np.uint8)
        frame[28:89, 47:61] = (115, 180, 24)
        frame[90:273, 47:61] = (250, 250, 250)
        value = detect_charge(frame)
        self.assertIsNotNone(value)
        self.assertAlmostEqual(value, 183 / 245, delta=0.04)

    def test_slider_detects_light_block_and_purple_handle(self):
        frame = np.full((60, 500, 3), (30, 25, 25), dtype=np.uint8)
        frame[17:43, 40:190] = (205, 190, 185)  # light moving block
        frame[6:54, 350:360] = (180, 150, 205)  # purple handle
        target = detect_target_center(frame)
        handle = detect_handle_center(frame)
        self.assertIsNotNone(target)
        self.assertIsNotNone(handle)
        self.assertAlmostEqual(target[0], 115, delta=8)
        self.assertAlmostEqual(handle[0], 355, delta=5)

    def test_handle_caps_visible_over_white_target(self):
        frame = np.full((64, 500, 3), (30, 28, 25), dtype=np.uint8)
        frame[17:47, 120:380] = (235, 235, 235)  # white target block
        frame[5:18, 245:255] = (78, 84, 98)      # dark lavender top cap
        frame[46:59, 245:255] = (78, 84, 98)     # dark lavender bottom cap
        frame[18:46, 245:255] = (232, 232, 235) # pale center over target
        handle = detect_handle_center(frame)
        self.assertIsNotNone(handle)
        self.assertAlmostEqual(handle[0], 250, delta=4)

    def test_progress_reads_coral_and_white_fill(self):
        coral = np.full((24, 300, 3), (35, 30, 35), dtype=np.uint8)
        coral[5:19, :120] = (255, 149, 112)
        value = detect_progress(coral)
        self.assertIsNotNone(value)
        self.assertAlmostEqual(value, 0.40, delta=0.04)

        white = np.full((24, 300, 3), (35, 30, 35), dtype=np.uint8)
        white[5:19, :210] = (255, 255, 255)
        value = detect_progress(white)
        self.assertIsNotNone(value)
        self.assertAlmostEqual(value, 0.70, delta=0.04)

    def test_fisch_style_hold_release_direction(self):
        # In this minigame, holding moves the pale bar right; releasing lets it drift left.
        self.assertTrue(fisch_should_hold(320, 200, 180, False))
        self.assertFalse(fisch_should_hold(80, 200, 180, True))
        # Within the deadband, preserve the current mouse state to avoid chatter.
        self.assertTrue(fisch_should_hold(205, 200, 180, True))
        self.assertFalse(fisch_should_hold(205, 200, 180, False))

    def test_fisch_detectors_separate_bar_and_fish_marker(self):
        frame = np.full((70, 500, 3), (25, 25, 24), dtype=np.uint8)
        frame[24:49, 35:235] = (230, 230, 230)  # wide control block
        frame[10:60, 345:355] = (82, 88, 112)   # muted purple/blue fish marker
        bar = detect_control_bar(frame)
        fish = detect_fish_marker(frame)
        self.assertIsNotNone(bar)
        self.assertIsNotNone(fish)
        self.assertAlmostEqual(bar[0], 135, delta=8)
        self.assertAlmostEqual(fish[0], 350, delta=5)


if __name__ == "__main__":
    unittest.main()
