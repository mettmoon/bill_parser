import contextlib
import csv
import io
from pathlib import Path
import tempfile
import unittest

from extract_shinhancard_html import extract_transactions, main, read_html


def row(amount='1,000'):
    cells = ['26.09.01', '체크<br>123', '상점, &amp; 가게', amount,
             '0', '100', '900', '0', '0', '']
    return '<tr>' + ''.join('<td>' + c + '</td>' for c in cells) + '</tr>'


def table(rows):
    return ( '<table class="tblList cardUseList"><thead><tr>'
        '<th rowspan="2">이용 일자</th><th rowspan="2">이용 카드</th>'
        '<th rowspan="2">이용가맹점</th><th colspan="4">이용금액</th>'
        '<th rowspan="2">입금하실 금액</th><th rowspan="2">캐시백</th>'
        '<th rowspan="2">포인트 적립율 (마이 신한)</th></tr><tr>'
        '<th>이용원금</th><th>수수료</th><th>할인금액</th><th>입금완납 금액</th>'
        '</tr></thead><tfoot><tr><th colspan="3">합 계 3건</th><td>1,000</td>'
        '</tr></tfoot><tbody>' + rows +
        '<tr><th colspan="3">체크 소계</th><td>1,000</td></tr></tbody></table>')


class ShinhancardTests(unittest.TestCase):
    def test_transactions(self):
        _, rows = extract_transactions(table(row() * 2 + row('-1,000')))
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0], rows[1])
        self.assertEqual(rows[0]['이용일자'], '2026-09-01')
        self.assertEqual(rows[0]['이용카드'], '체크 123')
        self.assertEqual(rows[0]['이용가맹점'], '상점, & 가게')
        self.assertEqual(rows[0]['이용원금'], '1000')
        self.assertEqual(rows[0]['입금완납금액'], '900')
        self.assertEqual(rows[2]['이용원금'], '-1000')
        for html in (table(''), table(row('invalid')), table(row()).replace('할인금액', '다른열'),
                     table(row()).replace('26.09.01', 'invalid'), '<html></html>',
                     table(row()).replace('<td>100</td>', '')):
            with self.assertRaises(ValueError):
                extract_transactions(html)

    def test_encodings_batch_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source = root / 'input'
            source.mkdir()
            output = root / 'output'
            for name, encoding in [('shinhancard_a.html', 'cp949'), ('SHINHANCARD_b.HTM', 'utf-8-sig')]:
                path = source / name
                path.write_bytes(table(row()).encode(encoding))
                self.assertEqual(read_html(path), table(row()))
            (source / 'shinhancard_bad.html').write_text('<html>unknown</html>')
            (source / 'shcard_ignore.html').write_text('unrelated')
            args = [str(source), '--output-dir', str(output)]
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(args), 1)
                path = output / 'shinhancard_a.csv'
                original = path.read_bytes()
                self.assertTrue(original.startswith(b'\xef\xbb\xbf'))
                self.assertEqual(main(args), 1)
                self.assertEqual(path.read_bytes(), original)
            self.assertEqual(len(list(output.iterdir())), 2)
            with path.open(encoding='utf-8-sig', newline='') as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['이용가맹점'], '상점, & 가게')


if __name__ == '__main__':
    unittest.main()
