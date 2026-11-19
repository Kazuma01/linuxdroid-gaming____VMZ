"""Testes da extração segura de XAPK, sem PySide6."""
import tempfile
import unittest
import zipfile
from pathlib import Path

from linuxdroid.services.xapk import extract_apk_members


class XapkExtractionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.destination = self.root / "out"
        self.destination.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def _make_zip(self, entries):
        path = self.root / "bundle.xapk"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, content in entries.items():
                archive.writestr(name, content)
        return path

    def test_extracts_only_apk_members_with_safe_names(self):
        path = self._make_zip({
            "base.apk": b"base",
            "splits/lang.pt.apk": b"lang",
            "README.txt": b"ignore",
        })
        extracted = extract_apk_members(path, self.destination)
        self.assertEqual(len(extracted), 2)
        self.assertEqual(extracted[0].name, "split_00_base.apk")
        self.assertEqual(extracted[1].name, "split_01_lang.pt.apk")
        self.assertEqual(extracted[0].read_bytes(), b"base")
        self.assertEqual(extracted[1].read_bytes(), b"lang")

    def test_rejects_empty_archive(self):
        path = self._make_zip({"README.txt": b"nada"})
        with self.assertRaisesRegex(ValueError, "não contém arquivos APK"):
            extract_apk_members(path, self.destination)

    def test_rejects_member_over_limit(self):
        path = self._make_zip({"huge.apk": b"123456"})
        with self.assertRaisesRegex(ValueError, "grande demais"):
            extract_apk_members(path, self.destination, max_member_bytes=4)

    def test_rejects_total_over_limit(self):
        path = self._make_zip({"a.apk": b"1234", "b.apk": b"5678"})
        with self.assertRaisesRegex(ValueError, "Total dos splits"):
            extract_apk_members(path, self.destination, max_total_bytes=6)

    def test_rejects_zip_bomb_ratio(self):
        path = self._make_zip({"bomb.apk": b"0" * 200000})
        with self.assertRaisesRegex(ValueError, "razão de compressão suspeita"):
            extract_apk_members(path, self.destination, max_compression_ratio=10)


if __name__ == "__main__":
    unittest.main()
