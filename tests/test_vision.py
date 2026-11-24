import unittest
import numpy as np

from core.config import TRACKING_FPS_OPTIONS, tracking_interval
from core.vision import detect_charge, detect_control_bar, detect_fish_marker, detect_handle_center, detect_progress, detect_target_center, fisch_edge_should_hold, fisch_should_hold


class VisionTests(unittest.TestCase):
    def test_tracking_fps_presets_have_expected_intervals(self):
        self.assertEqual(TRACKING_FPS_OPTIONS, (30, 60, 90, 120))
        self.assertAlmostEqual(tracking_interval(120), 1 / 120)
        self.assertAlmostEqual(tracking_interval("60"), 1 / 60)
        with self.assertRaises(ValueError):
            tracking_interval(144)

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

    def test_marker_still_detected_when_broad_lavender_reflection_overlaps(self):
        frame = np.full((130, 640, 3), (145, 105, 75), dtype=np.uint8)
        # A large low-saturation lavender reflection used to merge with the
        # marker mask and make the entire component too wide to accept.
        frame[20:112, 220:370] = (150, 140, 155)
        frame[45:86, 275:430] = (230, 230, 230)  # pale moving control block
        # The blue-gray marker remains visible at its caps; its center is
        # pale/neutral where it overlaps the control block.
        frame[22:48, 355:365] = (65, 73, 85)
        frame[48:86, 355:365] = (225, 225, 230)
        frame[86:110, 355:365] = (65, 73, 85)
        marker = detect_fish_marker(frame, expected_x=362)
        self.assertIsNotNone(marker)
        self.assertAlmostEqual(marker[0], 360, delta=4)

    def test_fish_marker_prefers_temporally_nearest_candidate(self):
        frame = np.full((70, 500, 3), (25, 25, 24), dtype=np.uint8)
        frame[7:63, 80:90] = (82, 88, 112)
        frame[7:63, 405:415] = (82, 88, 112)
        marker = detect_fish_marker(frame, expected_x=410)
        self.assertIsNotNone(marker)
        self.assertAlmostEqual(marker[0], 410, delta=4)

    def test_edge_tracker_switches_only_near_safe_zone_edges(self):
        # Stay with the current input while the fish is comfortably inside.
        self.assertFalse(fisch_edge_should_hold(540, 500, 150, False))
        self.assertTrue(fisch_edge_should_hold(470, 500, 150, True))
        # Turn toward the fish when its predicted position approaches an edge.
        self.assertTrue(fisch_edge_should_hold(570, 500, 150, False))
        self.assertFalse(fisch_edge_should_hold(430, 500, 150, True))

    def test_edge_tracker_predicts_relative_fish_and_bar_motion(self):
        # The fish is not at the edge yet, but is moving toward the right edge.
        self.assertTrue(fisch_edge_should_hold(
            530, 500, 150, False, fish_velocity=220, bar_velocity=0,
            prediction_seconds=0.20,
        ))
        # A bar already moving toward the fish avoids an unnecessary late input.
        self.assertFalse(fisch_edge_should_hold(
            555, 500, 150, False, fish_velocity=0, bar_velocity=260,
            prediction_seconds=0.20,
        ))

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
