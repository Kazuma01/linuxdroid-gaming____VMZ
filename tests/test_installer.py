"""Planejador de instalação: verificação antes de qualquer instalação real."""
import tempfile
import unittest
import zipfile
from pathlib import Path

from linuxdroid.services.installer import plan_apk_installation, plan_xapk_installation
from tests.test_apk_signature import key, make_apk


def make_xapk(path: Path, apks) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for apk in apks:
            archive.write(apk, arcname=apk.name)
    return path


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.destination = self.root / "destination"
        self.destination.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def test_xapk_with_same_signer_is_planned(self):
        first = make_apk(self.source / "base.apk", key(5))
        second = make_apk(self.source / "split.apk", key(5))
        xapk = make_xapk(self.root / "jogo.xapk", [first, second])

        plan = plan_xapk_installation(xapk, self.destination)

        self.assertTrue(plan.ok)
        self.assertEqual(len(plan.apks), 2)
        self.assertTrue(plan.verification.ok)
        self.assertTrue(all(path.exists() for path in plan.apks))
        self.assertEqual(plan.to_dict()["ok"], True)

    def test_different_signers_are_rejected_and_extracted_files_removed(self):
        first = make_apk(self.source / "base.apk", key(1))
        second = make_apk(self.source / "split.apk", key(2))
        xapk = make_xapk(self.root / "ruim.xapk", [first, second])

        plan = plan_xapk_installation(xapk, self.destination)

        self.assertFalse(plan.ok)
        self.assertEqual(plan.apks, ())
        self.assertEqual(list(self.destination.iterdir()), [])
        self.assertIn("assinantes diferentes", plan.message)

    def test_archive_without_apk_is_rejected(self):
        xapk = self.root / "vazio.xapk"
        with zipfile.ZipFile(xapk, "w") as archive:
            archive.writestr("readme.txt", "sem APK")
        plan = plan_xapk_installation(xapk, self.destination)
        self.assertFalse(plan.ok)
        self.assertIn("Extração recusada", plan.message)

    def test_single_apk_plan_requires_readable_signature(self):
        apk = make_apk(self.source / "base.apk", key(6))
        plan = plan_apk_installation(apk)
        self.assertTrue(plan.ok)
        self.assertEqual(plan.apks, (apk,))
        self.assertEqual(plan.verification.identities[0].scheme, "v2")

        inconclusive = self.source / "antigo.apk"
        inconclusive.write_bytes(b"sem bloco de assinatura")
        plan = plan_apk_installation(inconclusive)
        self.assertFalse(plan.ok)
        self.assertIn("inconclusiva", plan.message)


if __name__ == "__main__":
    unittest.main()
