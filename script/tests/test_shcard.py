import base64
import contextlib
import csv
import io
from pathlib import Path
import tempfile
import unittest

from cryptography.hazmat.decrepit.ciphers.algorithms import ARC4, SEED
from cryptography.hazmat.primitives.ciphers import Cipher, modes

from decrypt_shcard_html import (LICENSE, derive_key, decrypt_html,
                                 extract_transactions, matches, main)


def table(rows):
    return '<table class="tblList cardUseList"><tbody>' + rows + '</tbody></table>'


def row(date='26.09.01', principal='1,000'):
    cells = [date, '본인<br/>123', '상점, &amp; 가게', '&nbsp;', '3/1',
             principal, '0', '', '', '', '0.5%']
    return '<tr>' + ''.join('<td>' + c + '</td>' for c in cells) + '</tr>'


def wrapper(html, password='012345'):
    key = derive_key(password)
    data = LICENSE + html.encode()
    enc = Cipher(SEED(key[6:22]), modes.CBC(key[14:30])).encryptor()
    parts = [enc.update(data[:32]) + enc.finalize()]
    for offset in range(32, len(data), 1024):
        enc = Cipher(ARC4(key), mode=None).encryptor()
        parts.append(enc.update(data[offset:offset+1024]) + enc.finalize())
    return "var UNISAFESMAIL_DATA='" + base64.b64encode(b''.join(parts)).decode() + "';"


class ShinhanTests(unittest.TestCase):
    def test_chunk_boundaries_and_bad_password(self):
        # Multibyte text straddles RC4 block boundaries; decode only after joining.
        html = '<html>' + '한글테스트' * 1000 + '</html>'
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'SHCARD.HTM'
            path.write_text(wrapper(html))
            self.assertTrue(matches(path))
            self.assertEqual(decrypt_html(path, '012345'), html)
            with self.assertRaises(ValueError):
                decrypt_html(path, 'wrong')
            path.write_text("var UNISAFESMAIL_DATA='AAAA';")
            with self.assertRaises(ValueError):
                decrypt_html(path, '012345')

    def test_transactions_and_totals(self):
        _, rows = extract_transactions(table(row() * 2 + row(principal='-1,000') +
            '<tr><th colspan="5">일시불 소계</th><td>1,000</td></tr>'))
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0], rows[1])
        self.assertEqual(rows[0]['이용일자'], '2026-09-01')
        self.assertEqual(rows[0]['이용금액'], '')
        self.assertEqual(rows[0]['이번달내실원금'], '1000')
        self.assertEqual(rows[0]['이용카드'], '본인 123')
        self.assertEqual(rows[0]['이용가맹점'], '상점, & 가게')
        self.assertEqual(rows[2]['이번달내실원금'], '-1000')
        for html in ('<html>unknown</html>', table(row(date='invalid')),
                     table(row().replace('<td>0</td>', '')), table('')):
            with self.assertRaises(ValueError):
                extract_transactions(html)

    def test_batch_failure_continuation_and_existing_output(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source = root / 'input'
            source.mkdir()
            output = root / 'output'
            password = root / 'password.txt'
            password.write_text('012345\n')
            (source / 'shcard_a.html').write_text(wrapper(table(row()), 'wrong'))
            (source / 'shcard_b.html').write_text(wrapper(table(row())))
            (source / 'shinhancard_other.html').write_text('unrelated')
            args = [str(source), '--output-dir', str(output), '--password-file', str(password)]
            log = io.StringIO()
            with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                self.assertEqual(main(args), 1)
                path = output / 'shcard_b.csv'
                original = path.read_bytes()
                self.assertTrue(original.startswith(b'\xef\xbb\xbf'))
                self.assertEqual(main(args), 1)
                self.assertEqual(original, path.read_bytes())
            self.assertNotIn('012345', log.getvalue())
            self.assertEqual(len(list(output.iterdir())), 1)
            with path.open(encoding='utf-8-sig', newline='') as f:
                self.assertEqual(len(list(csv.DictReader(f))), 1)


if __name__ == '__main__':
    unittest.main()
