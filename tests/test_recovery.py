import unittest

from core.recovery import classify_failure, recovery_delay


class RecoveryTests(unittest.TestCase):
    def test_transient_detection_errors_are_retryable(self):
        self.assertEqual(classify_failure("ไม่พบแถบพลังในพื้นที่ B"), "retry")
        self.assertEqual(classify_failure("ตรวจไม่พบเส้นบอกตำแหน่งปลาต่อเนื่อง"), "retry")
        self.assertEqual(classify_failure("หน้ามินิเกมหายไปก่อน Progress ถึงระดับยืนยัน"), "retry")

    def test_focus_errors_pause_and_wait(self):
        self.assertEqual(classify_failure("Roblox ไม่ได้อยู่หน้าสุด — พักจนกว่าจะกลับมาอยู่หน้าสุด"), "focus")
        self.assertEqual(classify_failure("หน้าต่าง Roblox ถูกย่อหรือยังไม่พร้อม"), "focus")

    def test_configuration_and_closed_window_errors_are_fatal(self):
        self.assertEqual(classify_failure("ยังไม่ได้ตั้งค่าพื้นที่ slider"), "fatal")
        self.assertEqual(classify_failure("หน้าต่าง Roblox ถูกปิด"), "fatal")

    def test_manual_stop_is_never_retried(self):
        self.assertEqual(classify_failure("ผู้ใช้สั่งหยุดขณะรอมินิเกม"), "stop")

    def test_exponential_backoff_is_capped(self):
        self.assertEqual(recovery_delay(1, 2.5, 15), 2.5)
        self.assertEqual(recovery_delay(2, 2.5, 15), 5.0)
        self.assertEqual(recovery_delay(3, 2.5, 15), 10.0)
        self.assertEqual(recovery_delay(4, 2.5, 15), 15.0)
        self.assertEqual(recovery_delay(9, 2.5, 15), 15.0)


if __name__ == "__main__":
    unittest.main()
