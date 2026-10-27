"""
Unit tests for uHand UNO protocol framing, checksums, and controller logic.
"""

import os
import sys
import unittest

# Ensure HANDMOVE is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from controller import HandController, ProtocolType
import gestures


class TestUHandProtocol(unittest.TestCase):

    def test_official_checksum_examples(self):
        """Verify checksums match the official Hiwonder uHand UNO documentation."""
        # Example 1: AA 77 11 00 EE
        chk1 = HandController.calc_uhand_checksum(0x11, 0x00, b"")
        self.assertEqual(chk1, 0xEE)

        # Example 2: AA 77 11 06 5A 5A 5A 5A 5A 5A CC
        data2 = bytes([0x5A, 0x5A, 0x5A, 0x5A, 0x5A, 0x5A])
        chk2 = HandController.calc_uhand_checksum(0x11, 0x06, data2)
        self.assertEqual(chk2, 0xCC)

        # Example 3: AA 77 02 04 14 02 E8 03 F8
        data3 = bytes([0x14, 0x02, 0xE8, 0x03])
        chk3 = HandController.calc_uhand_checksum(0x02, 0x04, data3)
        self.assertEqual(chk3, 0xF8)

    def test_build_uhand_packet(self):
        """Verify packet formatting for uHand UNO."""
        ctrl = HandController(simulation_mode=True)
        pkt = ctrl.build_uhand_packet(0x01, [90, 90, 90, 90, 90, 90])
        # Header (2), Func (1), Len (1), 6 angles, Check (1) = 11 bytes
        self.assertEqual(len(pkt), 11)
        self.assertEqual(pkt[0], 0xAA)
        self.assertEqual(pkt[1], 0x77)
        self.assertEqual(pkt[2], 0x01)
        self.assertEqual(pkt[3], 0x06)
        self.assertEqual(pkt[4:10], bytes([90, 90, 90, 90, 90, 90]))
        # Expected checksum for 0x01 + 0x06 + 6*90 = 7 + 540 = 547 = 0x223 -> low byte 0x23 -> 0xFF - 0x23 = 0xDC
        self.assertEqual(pkt[10], 0xDC)

    def test_servo_clamping_and_trim(self):
        """Verify angle limits and calibration trims."""
        ctrl = HandController(simulation_mode=True)
        ctrl.trims[0] = 5     # +5 trim on thumb
        ctrl.inverted[1] = True  # invert index

        # Thumb: requested 100 -> 100 + 5 = 105
        hw_thumb = ctrl.to_hardware_angle(0, 100)
        self.assertEqual(hw_thumb, 105)

        # Index: requested 30 -> inverted to (180 - 30) = 150
        hw_index = ctrl.to_hardware_angle(1, 30)
        self.assertEqual(hw_index, 150)

        # Clamp max
        hw_clamp = ctrl.to_hardware_angle(0, 200)
        self.assertEqual(hw_clamp, 180)

        # Clamp min
        hw_clamp_min = ctrl.to_hardware_angle(0, -20)
        self.assertEqual(hw_clamp_min, 5)  # 0 clamped, then +5 trim

    def test_presets_coverage(self):
        """Verify preset gestures and sequences are properly structured."""
        for name, pose in gestures.PRESET_POSES.items():
            self.assertEqual(len(pose), 6, f"Pose {name} must have 6 angles")
            for angle in pose:
                self.assertTrue(0 <= angle <= 180, f"Angle {angle} out of bounds in {name}")

        for name, seq in gestures.PRESET_SEQUENCES.items():
            self.assertGreater(len(seq), 0, f"Sequence {name} cannot be empty")
            for pose, duration in seq:
                self.assertEqual(len(pose), 6)
                self.assertGreater(duration, 0)


if __name__ == "__main__":
    unittest.main()
