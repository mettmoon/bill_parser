import base64
import hashlib
from pathlib import Path
import tempfile
import unittest

from cryptography.hazmat.decrepit.ciphers.algorithms import SEED
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, modes

from decrypt_hyundaicard_html import decrypt_html, extract_transactions, write_csv, matches


def entry(date='260901', shop='테스트, 가맹점', amount='1,000'):
    return ("arUseDesc[loop++] = new UseDesc(loop, '" + date + "','본인', "
            "gf_Convert2ByteChar2('테스트카드'),gf_Convert2ByteChar2('" + shop + "'),'" + amount +
            "','0','0','" + amount + "','0','0','1.0','10','999999999','N','710113');")


def encrypted(parts, password):
    digest = hashlib.sha256(password.encode()).digest()
    key = hashlib.sha256(digest).digest()[:16]
    assignments = []
    for i, part in enumerate(parts):
        padder = padding.PKCS7(128).padder()
        data = padder.update(key + part) + padder.finalize()
        enc = Cipher(SEED(key), modes.CBC(digest[:16])).encryptor()
        blob = b'header-padding!!' + enc.update(data) + enc.finalize()
        assignments.append(f's[{i}] = "{base64.b64encode(blob).decode()}";')
    return '<script>' + ''.join(assignments) + '</script>'


class HyundaiTests(unittest.TestCase):
    def test_decryption_chunks_wrong_password_and_damage(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'HYUNDAICARD.HTML'
            data = '한글 명세서'.encode()
            path.write_text(encrypted([data[:2], data[2:]], '012345'))
            self.assertTrue(matches(path))
            self.assertEqual(decrypt_html(path, '012345'), '한글 명세서')
            with self.assertRaises(ValueError):
                decrypt_html(path, 'wrong')
            path.write_text('s[0] = "AAAA";')
            with self.assertRaises(ValueError):
                decrypt_html(path, '012345')

    def test_rows_preserved_and_totals_excluded(self):
        html = entry() * 2 + entry(shop="취소", amount='-1,000') + entry(date='', shop='총합계')
        headers, rows = extract_transactions(html)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0], rows[1])
        self.assertEqual(rows[0]['이용일'], '2026-09-01')
        self.assertEqual(rows[0]['이용금액'], '1000')
        self.assertEqual(rows[2]['이용금액'], '-1000')
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / 'result.csv'
            write_csv(destination, headers, rows)
            original = destination.read_bytes()
            self.assertTrue(original.startswith(b'\xef\xbb\xbf'))
            with self.assertRaises(FileExistsError):
                write_csv(destination, headers, [])
            self.assertEqual(destination.read_bytes(), original)
            self.assertEqual(len(list(Path(directory).iterdir())), 1)

    def test_escaped_strings_and_no_javascript_execution(self):
        _, rows = extract_transactions(entry(shop=r"Ａ\'가게\u0026상점"))
        self.assertEqual(rows[0]['이용가맹점'], "A'가게&상점")
        with self.assertRaises(ValueError):
            extract_transactions(entry().replace("'1,000'", "fetch('https://example.invalid')", 1))
        with self.assertRaises(ValueError):
            extract_transactions('<html>unknown format</html>')


if __name__ == '__main__':
    unittest.main()
