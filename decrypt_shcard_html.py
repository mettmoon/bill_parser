#!/usr/bin/env python3
"""신한카드 보안 HTML의 카드 사용내역을 파일별 CSV로 저장합니다."""

import argparse
import base64
from datetime import datetime
import hashlib
from html.parser import HTMLParser
import os
from pathlib import Path
import re
import sys

from decrypt_kt_pdfs import read_password
from decrypt_hyundaicard_html import write_csv

ROOT_DIR = Path(__file__).resolve().parent
LICENSE = b'<!--LIC_TO RIMESOFT-->'


def matches(path):
    return (path.is_file() and path.name.lower().startswith('shcard')
            and path.suffix.lower() in ('.html', '.htm'))


def derive_key(password):
    value = ('Copyright(C) 2014 rimesoft.com. All rights reserved.' + password).encode('latin-1')
    # UniSafeMail hashes byte strings nine times, truncating rounds 5 and 8.
    for length in (32, 32, 32, 32, 20, 32, 32, 31, 32):
        value = hashlib.sha256(value).digest()[:length]
    return value


def decrypt_html(source, password):
    from cryptography.hazmat.decrepit.ciphers.algorithms import SEED, ARC4
    from cryptography.hazmat.primitives.ciphers import Cipher, modes

    wrapper = source.read_bytes().decode('latin-1')
    match = re.search(r"\bUNISAFESMAIL_DATA\s*=\s*(['\"])([A-Za-z0-9+/=\s]+)\1", wrapper)
    if not match:
        raise ValueError('지원하지 않는 보안 HTML 형식입니다.')
    data = base64.b64decode(re.sub(r'\s+', '', match[2]), validate=True)
    if len(data) < 32:
        raise ValueError('암호화된 데이터가 손상되었습니다.')
    key = derive_key(password)
    decryptor = Cipher(SEED(key[6:22]), modes.CBC(key[14:30])).decryptor()
    head = decryptor.update(data[:32]) + decryptor.finalize()
    if not head.startswith(LICENSE):
        raise ValueError('암호가 일치하지 않거나 데이터가 손상되었습니다.')
    parts = [head]
    # The sender resets RC4 for every 1024-byte block after the SEED header.
    for offset in range(32, len(data), 1024):
        decryptor = Cipher(ARC4(key), mode=None).decryptor()
        parts.append(decryptor.update(data[offset:offset + 1024]) + decryptor.finalize())
    return b''.join(parts)[len(LICENSE):].decode('utf-8')


HEADERS = ['이용일자', '이용카드', '이용가맹점', '이용금액', '할부기간/회차',
           '이번달내실원금', '수수료(이자)', '이용혜택구분', '이용혜택금액',
           '결제후잔액', '포인트적립율(마이신한)']


class CardTableParser(HTMLParser):
    """Read only the statement's transaction table, without executing scripts."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.found = 0
        self.rows = []
        self.row = None
        self.cell = None
        self.section = ''

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'table':
            if self.depth:
                raise ValueError('사용내역 표에 지원하지 않는 중첩 표가 있습니다.')
            if 'cardUseList' in attrs.get('class', '').split():
                self.depth = 1
                self.found += 1
        if not self.depth:
            return
        if tag in ('thead', 'tbody', 'tfoot'):
            self.section = tag
        elif tag == 'tr':
            self.row = []
        elif tag in ('td', 'th') and self.row is not None:
            self.cell = [tag, attrs, []]
        elif tag == 'br' and self.cell is not None:
            self.cell[2].append(' ')

    def handle_data(self, data):
        if self.cell is not None:
            self.cell[2].append(data)

    def handle_endtag(self, tag):
        if not self.depth:
            return
        if tag in ('td', 'th') and self.cell is not None:
            kind, attrs, parts = self.cell
            self.row.append((kind, attrs, ' '.join(''.join(parts).split())))
            self.cell = None
        elif tag == 'tr' and self.row is not None:
            self.rows.append((self.section, self.row))
            self.row = None
        elif tag in ('thead', 'tbody', 'tfoot'):
            self.section = ''
        elif tag == 'table':
            self.depth = 0


def extract_transactions(html):
    parser = CardTableParser()
    parser.feed(html)
    parser.close()
    if parser.found != 1 or parser.depth:
        raise ValueError('지원하는 카드 사용내역 표를 찾지 못했습니다.')
    records = []
    for section, row in parser.rows:
        if section == 'thead' or not row:
            continue
        if row[0][0] == 'th' and re.search(r'(소계|합계)', row[0][2]):
            continue
        if len(row) != len(HEADERS) or any(
                a.get('colspan', '1') != '1' or a.get('rowspan', '1') != '1'
                for _, a, _ in row):
            raise ValueError('사용내역의 열 구성이 변경되었습니다.')
        values = [cell[2] for cell in row]
        if not re.fullmatch(r'\d{2}\.\d{2}\.\d{2}', values[0]):
            raise ValueError('이용일자 형식을 확인해 주세요.')
        values[0] = datetime.strptime('20' + values[0], '%Y.%m.%d').date().isoformat()
        for index in (3, 5, 6, 8, 9):
            values[index] = values[index].replace(',', '')
            if values[index] and not re.fullmatch(r'-?\d+(?:\.\d+)?', values[index]):
                raise ValueError('금액 형식을 확인해 주세요.')
        records.append(dict(zip(HEADERS, values)))
    if not records:
        raise ValueError('카드 사용내역이 없거나 지원하지 않는 형식입니다.')
    return HEADERS, records


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', nargs='?', type=Path, default=ROOT_DIR / 'input')
    parser.add_argument('--output-dir', type=Path, default=ROOT_DIR / 'output')
    parser.add_argument('--password-file', type=Path, default=ROOT_DIR / 'shcard_password.txt')
    args = parser.parse_args(argv)
    try:
        sources = sorted(p for p in args.folder.expanduser().iterdir() if matches(p))
        if not sources:
            print('shcard로 시작하는 HTML 파일이 없습니다.')
            return 0
        password = read_password(args.password_file.expanduser())
        output = args.output_dir.expanduser()
        output.mkdir(parents=True, exist_ok=True)
    except (OSError, ValueError):
        print('설정 오류: 입력 폴더와 암호 파일을 확인하세요.', file=sys.stderr)
        return 1
    succeeded = skipped = failed = 0
    for source in sources:
        destination = output / (source.stem + '.csv')
        if os.path.lexists(destination):
            print(f'건너뜀 (이미 존재): {destination.name}')
            skipped += 1
            continue
        try:
            headers, records = extract_transactions(decrypt_html(source, password))
            write_csv(destination, headers, records)
            print(f'완료: {destination.name} ({len(records)}건)')
            succeeded += 1
        except Exception as error:
            # Never expose passwords, plaintext, or third-party exception data.
            reason = str(error) if type(error) is ValueError and str(error).endswith('다.') else type(error).__name__
            print(f'실패: {source.name} ({reason})', file=sys.stderr)
            failed += 1
    print(f'처리 결과: 성공 {succeeded}개 / 건너뜀 {skipped}개 / 실패 {failed}개')
    return 1 if failed else 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print('\n처리가 취소되었습니다.', file=sys.stderr)
        sys.exit(130)
