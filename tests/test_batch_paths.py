from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.batch import assign_output_names, discover_pdfs


class BatchPathTests(unittest.TestCase):
    def test_recursive_discovery_excludes_output_subtree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_dir = root / "input"
            output_dir = input_dir / "results"
            output_dir.mkdir(parents=True)
            source = input_dir / "source.pdf"
            generated = output_dir / "source.searchable.pdf"
            source.write_bytes(b"source")
            generated.write_bytes(b"generated")

            discovered = discover_pdfs(
                input_dir,
                recursive=True,
                excluded_dir=output_dir.resolve(),
            )

            self.assertEqual(discovered, [source])

    def test_output_names_avoid_case_insensitive_collisions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            input_dir = Path(directory)
            upper = input_dir / "Report.pdf"
            lower = input_dir / "report.pdf"
            upper.write_bytes(b"upper")
            lower.write_bytes(b"lower")

            names = assign_output_names([upper, lower], input_dir)

            self.assertNotEqual(names[upper].casefold(), names[lower].casefold())
            self.assertTrue(names[upper].startswith("Report_"))
            self.assertTrue(names[lower].startswith("report_"))


if __name__ == "__main__":
    unittest.main()
