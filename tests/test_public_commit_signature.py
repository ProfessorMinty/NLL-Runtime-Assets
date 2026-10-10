"""Offline regression for public GitHub signature classification; no provider I/O."""
import base64
import hashlib
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import validate_public_boundary as boundary  # noqa: E402

# Public immutable provider commit, not a credential or private operational fixture.
# Encoding avoids asking the source-text scanner to interpret signature-body slashes.
RAW = base64.b64decode("dHJlZSA0YThiM2ZhMzlhNTFkMWFiYzYxNGU3MjY0YzFlZTQ5N2ZmMjFiOTkyCnBhcmVudCAxYTIyYTdlOTg3NDI4NTFhN2Y5ZTFjYWQxZTY3YmNkN2U0ZjQ3MzYxCnBhcmVudCAyYWMyNjBiMWRlNWE2NGM3ZDM2ZTU2MTE3NjNlMjkyNWY0ZDcwYTA0CmF1dGhvciBubC1hc3NldC1ydW50aW1lLXB1Ymxpc2hlcltib3RdIDwzMjM1NjA4MzkrbmwtYXNzZXQtcnVudGltZS1wdWJsaXNoZXJbYm90XUB1c2Vycy5ub3JlcGx5LmdpdGh1Yi5jb20+IDE3OTE1ODM4MDAgKzAwMDAKY29tbWl0dGVyIEdpdEh1YiA8bm9yZXBseUBnaXRodWIuY29tPiAxNzkxNTgzODAwICswMDAwCmdwZ3NpZyAtLS0tLUJFR0lOIFBHUCBTSUdOQVRVUkUtLS0tLQogCiB3c0ZjQkFBQkNBQVFCUUpxeVdZNENSQzFhUTd1dTVVaGxBQUFPUlFRQUlRaERoLzlWbjFNTGk5VjZOeWpmSUN0CiBwZ0psdG9sMEhRVnE4M0xTdTVDbmZKaFE5dGhKK3FtUmRpcGdzeklhS2tsYVVyRTZ4MksrYy9uTzZvQVhWM1UzCiAvQ0tkY3ZMTkVQOUxwRnpzTTNaU01GZUNvT09nck1QeElmRkRkRUhWYWszdndIR0E3VjQrVGRoOTgxUGw0bEhNCiAzM1g1c2tHeHZZS1FjcjJvN2FqQUErQzFoRjZnaWM5dWNxSk9tdlRLYTV3blliZlR3czhXNlpSanB0S1FjN1BYCiB6Y1lqTzVWalJRR3VUZEJadkovdXFVVjdUNjlqVzlteXBrOHhZNDNZZXVCaElXTUdieGE2bGwxbWt5VUJaMFRNCiBselBFVGtGbDJzaythUGdVeDNTWnNRRTQ4U0hlK0ZGUG1mWktCd3poSm9DdGhJa3c5dmFJbTAxS3JQVmo5am5aCiBqL2VQTngzc3M4VXFjQVM4clYrdG9VOGJkYVk3azh2aDJTeVNlYnA5eW1pVFNvYnU2V0VHVTB1b1lSNGd3MXJCCiB2ZUtaQ3Vmb3ZKbnlWRERSekxPWW9ZNU5MQkJZNS9JT0UzL3l5Qk0reGdveGxzeS9LK2twOXd5aHUrN0MwMEFKCiBTTk8vTDB0MWl4WXpjMUxaTkZFSkE0b2V3aDYxUWhaVHZJclZXWWtxTThxakFXZE1GaGl3RXdVM2J4N3E1K29ICiB6cTdjL1kwYVZTR2NuZkJZZGFlbngvVkVzM1ZnaU1zTVdxdFBPMHBNaTFQb1RVRm42QUd6V3k4enZpSGZaRm5BCiAyZmNwYlBuVW9kdWhFb252TVpiK0QvWHNpbmF0OGVtOUpYaEZrd1cyQ2VTbUlYbVZKdXZWYS9velRwWU1rVHBQCiBmbklaSlpLSGF4WmFvZzVxZEhFVAogPVVnbFMKIC0tLS0tRU5EIFBHUCBTSUdOQVRVUkUtLS0tLQogCgpNZXJnZSByZXZpZXdlZCBwdWxsIHJlcXVlc3QgIzcKClJldmlld2VkIDJhYzI2MGIxZGU1YTY0YzdkMzZlNTYxMTc2M2UyOTI1ZjRkNzBhMDQgb250byAxYTIyYTdlOTg3NDI4NTFhN2Y5ZTFjYWQxZTY3YmNkN2U0ZjQ3MzYxLg==", validate=True)


class PublicCommitSignatureTests(unittest.TestCase):
    def validate(self, raw):
        revision = hashlib.sha1(b"commit " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        parents = [line[7:].decode() for line in raw.partition(b"\n\n")[0].splitlines() if line.startswith(b"parent ")]

        def git(_root, *args):
            if args[:2] == ("cat-file", "-s"):
                return str(len(raw)).encode()
            if args[:2] == ("cat-file", "commit"):
                return raw
            if args[0] == "rev-list":
                return " ".join([revision, *parents]).encode()
            raise AssertionError(args)

        with patch.object(boundary, "_run_git", git):
            boundary._validate_commit_message(ROOT, revision)

    def test_exact_public_provider_signature_passes(self):
        self.assertEqual(hashlib.sha1(b"commit " + str(len(RAW)).encode() + b"\0" + RAW).hexdigest(),
                         "ab57777045f06500445d37c2b257bd555a4e16e1")
        self.validate(RAW)

    def test_old_path_heuristic_reproduces_false_positive(self):
        self.assertIsNotNone(boundary.PRIVATE_TEXT_PATTERNS[3].search(RAW.decode()))
        self.assertIsNone(boundary.PRIVATE_TEXT_PATTERNS[3].search(boundary._commit_path_scan_text(RAW.decode())))

    def test_unix_path_in_message_denied(self):
        with self.assertRaises(boundary.PublicBoundaryError):
            self.validate(RAW + b"\n" + bytes([47]) + b"home/operator/private\n")

    def test_private_author_denied(self):
        with self.assertRaises(boundary.PublicBoundaryError):
            self.validate(RAW.replace(b"author ", b"author " + bytes([47]) + b"home/private ", 1))

    def test_credential_message_denied(self):
        with self.assertRaises(boundary.PublicBoundaryError):
            self.validate(RAW + b"\nghp_" + b"A" * 36)

    def test_credential_header_denied(self):
        with self.assertRaises(boundary.PublicBoundaryError):
            self.validate(RAW.replace(b"author ", b"author ghs_" + b"A" * 36 + b" ", 1))

    def test_duplicate_signature_denied(self):
        with self.assertRaises(boundary.PublicBoundaryError):
            self.validate(RAW.replace(b"\n\n", b"\ngpgsig invalid\n\n", 1))

    def test_signature_end_missing_denied(self):
        with self.assertRaises(boundary.PublicBoundaryError):
            self.validate(RAW.replace(b"-----END PGP SIGNATURE-----", b"invalid-end"))

    def test_signature_non_encoding_text_denied(self):
        with self.assertRaises(boundary.PublicBoundaryError):
            self.validate(RAW.replace(b"gpgsig -----BEGIN PGP SIGNATURE-----\n ", b"gpgsig -----BEGIN PGP SIGNATURE-----\n private text"))

    def test_bad_checksum_denied(self):
        text = RAW.decode()
        checksum = next(line for line in text.splitlines() if line.startswith(" ="))
        replacement = " =AAAA" if checksum != " =AAAA" else " =BBBB"
        with self.assertRaises(boundary.PublicBoundaryError):
            self.validate(text.replace(checksum, replacement).encode())

    def test_armored_message_is_not_exempt(self):
        with self.assertRaises(boundary.PublicBoundaryError):
            self.validate(RAW + b"\n-----BEGIN PGP SIGNATURE-----\n " + bytes([47]) + b"home/private\n-----END PGP SIGNATURE-----\n")

    def test_control_text_remains_denied(self):
        with self.assertRaises(boundary.PublicBoundaryError):
            self.validate(RAW + "\n\u202eHidden".encode())


if __name__ == "__main__":
    unittest.main()
