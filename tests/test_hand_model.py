"""
Tests for the uHand UNO 3D model geometry and kinematics (no OpenGL needed).
"""

import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from hand_model import kinematics as K
from hand_model.scene import build_parts, scene_bounds

OPEN = (180, 180, 180, 180, 180, 90)
FIST = (0, 0, 0, 0, 0, 90)


class TestHandKinematics(unittest.TestCase):

    def test_open_fingers_point_up(self):
        tips = K.fingertip_positions(OPEN)
        knuckle_z = K.WRIST_Z + K.HAND_BASE_Z + K.PALM_H
        for name in ("index", "middle", "ring", "pinky"):
            self.assertGreater(tips[name][2], knuckle_z + 60, name)

    def test_hand_length_matches_spec(self):
        # Hiwonder lists the hand as 165 mm long (wrist to middle fingertip).
        tips = K.fingertip_positions(OPEN)
        length = tips["middle"][2] - (K.WRIST_Z + K.HAND_BASE_Z)
        self.assertAlmostEqual(length, 165.0, delta=10.0)

    def test_fist_curls_toward_palm(self):
        open_tips = K.fingertip_positions(OPEN)
        fist_tips = K.fingertip_positions(FIST)
        for name in ("index", "middle", "ring", "pinky"):
            self.assertLess(fist_tips[name][2], open_tips[name][2] - 50, name)
            self.assertGreater(fist_tips[name][1], 0.0, f"{name} should curl to the palm side (+Y)")

    def test_each_servo_moves_only_its_finger(self):
        base = K.fingertip_positions(OPEN)
        for spec in K.FINGERS:
            pose = list(OPEN)
            pose[spec.channel] = 0
            moved = K.fingertip_positions(pose)
            for other in K.FINGERS:
                delta = np.linalg.norm(moved[other.name] - base[other.name])
                if other.name == spec.name:
                    self.assertGreater(delta, 20.0)
                else:
                    self.assertAlmostEqual(delta, 0.0, places=6)

    def test_wrist_rotates_about_vertical_axis(self):
        centre = K.fingertip_positions(OPEN)["middle"]
        turned = K.fingertip_positions((180, 180, 180, 180, 180, 180))["middle"]
        self.assertAlmostEqual(centre[2], turned[2], places=6)
        self.assertAlmostEqual(np.hypot(*centre[:2]), np.hypot(*turned[:2]), places=6)
        self.assertAlmostEqual(K.wrist_yaw_deg(180), 90.0)
        self.assertAlmostEqual(K.wrist_yaw_deg(0), -90.0)

    def test_out_of_range_angles_are_clamped(self):
        self.assertEqual(K.curl_fraction(-30), 1.0)
        self.assertEqual(K.curl_fraction(400), 0.0)

    def test_right_hand_thumb_on_minus_x(self):
        tips = K.fingertip_positions(OPEN)
        self.assertLess(tips["thumb"][0], tips["index"][0])
        self.assertLess(tips["index"][0], tips["pinky"][0])


class TestHandScene(unittest.TestCase):

    def test_parts_build_with_valid_meshes(self):
        parts = build_parts()
        links = K.link_transforms(OPEN)
        self.assertGreater(len(parts), 20)
        for p in parts:
            self.assertIn(p.link, links, p.name)
            self.assertEqual(p.mesh.vertices.shape, p.mesh.normals.shape, p.name)
            self.assertEqual(len(p.mesh.vertices) % 3, 0, p.name)
            self.assertTrue(np.all(np.isfinite(p.mesh.vertices)), p.name)
            lengths = np.linalg.norm(p.mesh.normals, axis=1)
            self.assertTrue(np.allclose(lengths, 1.0, atol=1e-3), p.name)

    def test_scene_sits_on_the_table(self):
        lo, hi = scene_bounds(build_parts())
        self.assertAlmostEqual(lo[2], 0.0, delta=0.5)
        self.assertGreater(hi[2], 250.0)


if __name__ == "__main__":
    unittest.main()
