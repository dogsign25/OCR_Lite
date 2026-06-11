from __future__ import annotations

import unittest

from app.services.ocr_service import OcrResult
from app.services.ocr_verifier import select_verified_result


class OcrVerifierTests(unittest.TestCase):
    def test_prefers_clean_consensus_over_high_confidence_typo(self) -> None:
        result = select_verified_result(
            {
                "balanced": OcrResult("소켓 프로그래밍 테스트", 91.0),
                "uniform": OcrResult("소켓 프로그래밍 테스트", 83.0),
                "sparse": OcrResult("소켓 프로그밍 테스드", 99.0),
            }
        )

        self.assertEqual(result.text, "소켓 프로그래밍 테스트")
        self.assertEqual(result.selected_candidate, "balanced")

    def test_empty_candidate_does_not_win(self) -> None:
        result = select_verified_result(
            {
                "empty": OcrResult("", 100.0),
                "text": OcrResult("readable text", 55.0),
            }
        )

        self.assertEqual(result.selected_candidate, "text")


if __name__ == "__main__":
    unittest.main()
