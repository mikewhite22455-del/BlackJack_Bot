import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5 import QtWidgets  # noqa: E402
from casinotime_app import CasinoTimeWindow  # noqa: E402


class CasinoTimeGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.window = CasinoTimeWindow()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def test_unconfirmed_rule_blocks_practice_start(self):
        self.window.begin.click()
        self.assertIsNone(self.window.table)
        self.assertIn("labelled assumption", self.window.status.text())

    def test_full_session_cut_reset_and_export_visibility(self):
        self.window.ten_rule.setCurrentIndex(1)
        self.window.cut.setValue(52)
        self.window.begin.click()
        for _ in range(10):
            self.window.actions["Deal"].click()
            if self.window.table.phase != "settled":
                self.assertIn("Hidden", self.window.display.toPlainText())
                self.assertFalse(self.window.begin.isEnabled())
                self.window.actions["Finish using basic strategy"].click()
            self.assertEqual(self.window.table.phase, "settled")
            self.assertTrue(self.window.actions["Deal"].isEnabled())
        self.assertGreater(self.window.table.shoe.number, 1)
        self.assertIn("Next-card probabilities", self.window.probabilities.text())


if __name__ == "__main__":
    unittest.main()
