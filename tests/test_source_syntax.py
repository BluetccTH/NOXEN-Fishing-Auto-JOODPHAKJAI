from pathlib import Path
import unittest


class SourceSyntaxTests(unittest.TestCase):
    def test_core_and_app_sources_compile(self):
        root = Path(__file__).resolve().parents[1]
        source_files = (
            "app.py",
            "core/config.py",
            "core/engine.py",
            "core/vision.py",
        )
        for relative_path in source_files:
            path = root / relative_path
            with self.subTest(path=relative_path):
                source = path.read_text(encoding="utf-8")
                compile(source, str(path), "exec")


if __name__ == "__main__":
    unittest.main()
