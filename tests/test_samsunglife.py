import base64
import csv
import hashlib
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO

from cryptography.hazmat.decrepit.ciphers.algorithms import SEED
from cryptography.hazmat.primitives.ciphers import Cipher, modes
from cryptography.hazmat.primitives.padding import PKCS7

import decrypt_samsunglife_html as samsung


def fixture():
    labels = ''.join('<th>' + value + '</th>' for value in samsung.TABLE_HEADERS)
    payment = ('<tr><td rowspan="2">2026.09.10</td>'
               '<td rowspan="2">2026.08.10<br>~2026.09.09</td><td>1,234</td></tr>'
               '<tr><td>234</td></tr>')
    return ('<table summary="고객명, 고객번호, 차기납입일"><tr><th>고객명</th><td>테스트</td>'
            '<th>고객번호</th><td>00123</td><th>차기납입일</th><td>2026.10.10</td></tr></table>'
            '<table summary="대출명, 계약일자"><thead><tr>' + labels + '</tr></thead><tbody>'
            '<tr><td>모기지론(상품)<br>(원리균등)</td><td>2020.01.01</td><td>2050.01.01</td>'
            '<td>10,000</td><td>9,000</td><td>4.15</td><td colspan="3"><table><tbody>'
            + payment * 2 + '</tbody></table></td></tr></tbody></table>')


def encrypt(data, key, iv):
    padder = PKCS7(128).padder()
    cipher = Cipher(SEED(key), modes.CBC(iv)).encryptor()
    return cipher.update(padder.update(data) + padder.finalize()) + cipher.finalize()


def wrapper(html, password='001234', corrupt=False):
    plain = html.encode()
    salt, iv, key = b'12345678', b'0123456789abcdef', b'abcdef0123456789'
    digest = hashlib.sha1(password.encode() + salt).digest()
    for _ in range(99):
        digest = hashlib.sha1(digest).digest()
    envelope = (bytes.fromhex('503548304606082a831a8c9a44010f303a301a06092a864886f70d01050c300d0408')
                + salt + bytes.fromhex('020164301c06082a831a8c9a4401040410') + iv
                + b'\x20' + encrypt(key, digest[:16], iv))
    header = 'X-XEI_PWD_TYPE: 1\nX-XE_KEY: 10: ' + base64.b64encode(envelope).decode() + '\nContent-Type: application/x-pwd'
    result = '<input id="smime_header" value="' + base64.b64encode(header.encode()).decode() + '">'
    check = bytes(32) if corrupt else hashlib.sha256(plain).digest()
    # Split within UTF-8 characters too: decoding must happen after reassembly.
    for i, part in enumerate((plain[:101], plain[101:])):
        result += '\ncipher[%d] = "%s";' % (i, base64.b64encode(encrypt(check + part, key, bytes(16))).decode())
    return result


class SamsungLifeTests(unittest.TestCase):
    def test_nested_payments_and_normalization(self):
        headers, rows = samsung.extract_transactions(fixture())
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], rows[1])  # Preserve genuine identical payments.
        self.assertEqual(len(headers), 15)
        self.assertEqual(rows[0]['고객번호'], '00123')
        self.assertEqual(rows[0]['대출명'], '모기지론(상품)')
        self.assertEqual(rows[0]['상환방법'], '원리균등')
        self.assertEqual(rows[0]['납입기간종료'], '2026-09-09')
        self.assertEqual(rows[0]['총납입금액'], '1234')
        self.assertEqual(rows[0]['원금상환금액'], '234')

    def test_unsupported_tables_fail(self):
        for html in (fixture().replace('총납입금액', '다른열'),
                     fixture().replace('<tr><td>234</td></tr>', ''),
                     fixture().replace('2026.09.09', '2026.09.31'), '<html></html>'):
            with self.subTest(html=html[:30]), self.assertRaises(ValueError):
                samsung.extract_transactions(html)

    def test_decryption_password_integrity_and_chunks(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'SamsungLife.html'
            source.write_text(wrapper(fixture()))
            self.assertEqual(samsung.decrypt_html(source, '001234'), fixture())
            with self.assertRaises(ValueError):
                samsung.decrypt_html(source, 'wrong')
            for content in (wrapper(fixture(), corrupt=True),
                            wrapper(fixture()).replace('cipher[1]', 'cipher[2]'),
                            wrapper(fixture()).replace('cipher[1]', 'cipher[0]')):
                source.write_text(content)
                with self.assertRaises(ValueError):
                    samsung.decrypt_html(source, '001234')

    def test_cli_continues_and_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'SamsungLife-bad.html').write_text('unsupported')
            source = root / 'SAMSUNGLIFE-good.HTM'
            original = wrapper(fixture())
            source.write_text(original)
            password = root / 'password.txt'
            password.write_text('001234\n')
            output = root / 'out'
            args = [str(root), '--password-file', str(password), '--output-dir', str(output)]
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(samsung.main(args), 1)
            destination = output / 'SamsungLife_20261010.csv'
            self.assertTrue(destination.read_bytes().startswith(b'\xef\xbb\xbf'))
            with destination.open(encoding='utf-8-sig', newline='') as stream:
                self.assertEqual(len(list(csv.DictReader(stream))), 2)
            destination.write_text('preserved')
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(samsung.main(args), 1)
            self.assertEqual(destination.read_text(), 'preserved')
            first_copy = output / 'SamsungLife_20261010_1.csv'
            self.assertTrue(first_copy.exists())
            copy_bytes = first_copy.read_bytes()
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(samsung.main(args), 1)
            self.assertEqual(first_copy.read_bytes(), copy_bytes)
            self.assertEqual((output / 'SamsungLife_20261010_2.csv').read_bytes(), copy_bytes)
            self.assertEqual(len(list(output.glob('*.csv'))), 3)
            self.assertEqual(source.read_text(), original)
            self.assertFalse((output / 'SamsungLife-bad.csv').exists())


if __name__ == '__main__':
    unittest.main()
