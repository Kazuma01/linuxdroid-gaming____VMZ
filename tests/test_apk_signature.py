"""Verificação de identidade de assinatura — blocos sintéticos, sem APK real."""
import hashlib
import struct
import tempfile
import unittest
from pathlib import Path

from linuxdroid.services.apk_signature import (
    SIGNING_BLOCK_MAGIC,
    V2_BLOCK_ID,
    V3_BLOCK_ID,
    inspect_apk,
    verify_split_signatures,
)


def lp(data: bytes) -> bytes:
    return struct.pack("<I", len(data)) + data


def signing_block_value(public_key: bytes, *, with_sdk: bool) -> bytes:
    signed_data = b"\x11" * 24
    signatures = lp(b"\x22" * 16)
    signer = lp(signed_data)
    if with_sdk:
        signer += struct.pack("<II", 24, 999999)
    signer += signatures + lp(public_key)
    return lp(lp(signer))


def make_apk(path: Path, public_key: bytes, *, block_id=V2_BLOCK_ID, with_sdk=False) -> Path:
    value = signing_block_value(public_key, with_sdk=with_sdk)
    pair = struct.pack("<Q", 4 + len(value)) + struct.pack("<I", block_id) + value
    block_size = len(pair) + 24
    block = struct.pack("<Q", block_size) + pair + struct.pack("<Q", block_size) + SIGNING_BLOCK_MAGIC
    block_start = 4096
    cd_offset = block_start + len(block)
    eocd = struct.pack("<4sHHHHIIH", b"PK\x05\x06", 0, 0, 0, 0, 0, cd_offset, 0)
    path.write_bytes(b"X" * block_start + block + eocd)
    return path


def key(seed: int) -> bytes:
    return b"\x30" + bytes([seed]) + bytes((seed + i) % 256 for i in range(190))


class ApkSignatureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dir = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_v2_identity_uses_public_key_sha256(self):
        public = key(7)
        apk = make_apk(self.dir / "split.apk", public)
        identity = inspect_apk(apk)
        self.assertIsNotNone(identity)
        self.assertEqual(identity.scheme, "v2")
        self.assertEqual(identity.fingerprint, hashlib.sha256(public).hexdigest())
        self.assertIn("não é verificação criptográfica", identity.note)

    def test_v3_layout_is_supported(self):
        public = key(11)
        apk = make_apk(self.dir / "v3.apk", public, block_id=V3_BLOCK_ID, with_sdk=True)
        identity = inspect_apk(apk)
        self.assertIsNotNone(identity)
        self.assertEqual(identity.scheme, "v3")
        self.assertEqual(identity.fingerprint, hashlib.sha256(public).hexdigest())

    def test_same_signer_across_splits_is_accepted(self):
        first = make_apk(self.dir / "base.apk", key(3))
        second = make_apk(self.dir / "split_01.apk", key(3))
        result = verify_split_signatures([first, second])
        self.assertTrue(result.ok)
        self.assertEqual(len(result.identities), 2)
        self.assertIn("mesmo assinante", result.message)
        self.assertEqual(result.to_dict()["ok"], True)

    def test_different_signers_are_rejected(self):
        first = make_apk(self.dir / "base.apk", key(3))
        second = make_apk(self.dir / "split_01.apk", key(9))
        result = verify_split_signatures([first, second])
        self.assertFalse(result.ok)
        self.assertIn("assinantes diferentes", result.message)

    def test_missing_block_is_inconclusive_and_fails_closed(self):
        apk = self.dir / "v1_only.apk"
        apk.write_bytes(b"X" * 4096 + struct.pack("<4sHHHHIIH", b"PK\x05\x06", 0, 0, 0, 0, 0, 4096, 0))
        self.assertIsNone(inspect_apk(apk))
        result = verify_split_signatures([apk])
        self.assertFalse(result.ok)
        self.assertIn("inconclusiva", result.message)

    def test_corrupt_block_is_inconclusive(self):
        apk = make_apk(self.dir / "corrupt.apk", key(4))
        data = bytearray(apk.read_bytes())
        magic_at = data.index(SIGNING_BLOCK_MAGIC)
        data[magic_at] = ord("Z")
        apk.write_bytes(bytes(data))
        self.assertIsNone(inspect_apk(apk))

    def test_no_splits_is_rejected(self):
        result = verify_split_signatures([])
        self.assertFalse(result.ok)
        self.assertIn("Nenhum split", result.message)


if __name__ == "__main__":
    unittest.main()
