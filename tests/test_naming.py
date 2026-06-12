from __future__ import annotations

import unittest

from app.services.naming import safe_stem


class NamingTests(unittest.TestCase):
    def test_avoids_windows_reserved_names(self) -> None:
        self.assertEqual(safe_stem("CON.pdf"), "_CON")
        self.assertEqual(safe_stem("lpt1.PDF"), "_lpt1")

    def test_normalizes_unicode_compatibility_characters(self) -> None:
        self.assertEqual(safe_stem("Ｒｅｐｏｒｔ.pdf"), "Report")


if __name__ == "__main__":
    unittest.main()
