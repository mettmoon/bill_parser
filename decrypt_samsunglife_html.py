#!/usr/bin/env python3
"""삼성생명 보안 HTML의 대출 원리금 납입내역을 파일별 CSV로 저장합니다."""

import argparse
import base64
import os
import sys
from datetime import datetime
import hashlib
import hmac
from html.parser import HTMLParser
from pathlib import Path
import re

from decrypt_hyundaicard_html import write_csv
from decrypt_kt_pdfs import read_password

ROOT_DIR = Path(__file__).resolve().parent


def matches(path):
    return (path.is_file() and path.name.lower().startswith('samsunglife')
            and path.suffix.lower() in ('.html', '.htm'))


def seed_decrypt(data, key, iv):
    from cryptography.hazmat.decrepit.ciphers.algorithms import SEED
    from cryptography.hazmat.primitives.ciphers import Cipher, modes
    from cryptography.hazmat.primitives.padding import PKCS7

    cipher = Cipher(SEED(key), modes.CBC(iv)).decryptor()
    plain = cipher.update(data) + cipher.finalize()
    unpadder = PKCS7(128).unpadder()
    return unpadder.update(plain) + unpadder.finalize()


class HeaderParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.headers = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'input' and attrs.get('id') == 'smime_header':
            self.headers.append(attrs.get('value', ''))


def decode64(value):
    return base64.b64decode(re.sub(r'\s+', '', value), validate=True)


def decrypt_html(source, password):
    """XecureExpress P5 envelope: iterated SHA-1, SEED-CBC, SHA-256 body check.

    Accept only the observed DER layout (8-byte salt, 1-byte iteration count,
    SEED-CBC OID and 16-byte IV). Unknown envelopes fail closed.
    """
    wrapper = source.read_text(encoding='utf-8-sig')
    parser = HeaderParser()
    parser.feed(wrapper)
    if len(parser.headers) != 1:
        raise ValueError('지원하지 않는 보안 HTML 형식입니다.')
    header = decode64(parser.headers[0]).decode('ascii')
    match = re.search(r'^X-XE_KEY:\s*10:\s*(\S+)\s*$', header, re.M)
    if (not match or not re.search(r'^X-XEI_PWD_TYPE:\s*1\s*$', header, re.M)
            or 'X-XE_ALG:' in header or 'Content-Type: application/x-pwd' not in header):
        raise ValueError('지원하지 않는 보안 HTML 형식입니다.')
    envelope = decode64(match[1])
    # Exact DER tags/lengths/OIDs; salt, iterations, IV and encrypted key vary.
    pattern = (re.escape(bytes.fromhex('503548304606082a831a8c9a44010f303a301a06092a864886f70d01050c300d0408'))
               + b'(.{8})' + re.escape(bytes.fromhex('0201')) + b'([\x01-\x7f])'
               + re.escape(bytes.fromhex('301c06082a831a8c9a4401040410')) + b'(.{16})'
               + re.escape(b'\x20') + b'(.{32})')
    fields = re.fullmatch(pattern, envelope, re.S)
    if fields is None:
        raise ValueError('지원하지 않는 암호화 키 형식입니다.')
    salt, iterations, iv, encrypted_key = fields.groups()
    digest = hashlib.sha1(password.encode('utf-8') + salt).digest()
    for _ in range(iterations[0] - 1):
        digest = hashlib.sha1(digest).digest()
    chunks = re.findall(r'\bcipher\[(\d+)\]\s*=\s*([\'"])([A-Za-z0-9+/=\s]+)\2', wrapper)
    if not chunks or [int(c[0]) for c in chunks] != list(range(len(chunks))):
        raise ValueError('암호화된 본문 조각이 누락되거나 순서가 잘못되었습니다.')
    try:
        key = seed_decrypt(encrypted_key, digest[:16], iv)
        if len(key) != 16:
            raise ValueError()
        parts = [seed_decrypt(decode64(c[2]), key, bytes(16)) for c in chunks]
        plain = b''.join(part[32:] for part in parts)
        checksum = hashlib.sha256(plain).digest()
        if any(len(part) < 32 or not hmac.compare_digest(part[:32], checksum) for part in parts):
            raise ValueError()
        return plain.decode('utf-8')
    except ValueError:
        raise ValueError('암호가 일치하지 않거나 데이터가 손상되었습니다.') from None


class Node:
    def __init__(self, tag='', attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []

    def text(self):
        return ''.join(c.text() if isinstance(c, Node) else c for c in self.children)

    def find(self, tag):
        for child in self.children:
            if isinstance(child, Node):
                if child.tag == tag:
                    yield child
                yield from child.find(tag)


class TableParser(HTMLParser):
    """Keep table nesting so loan rows cannot mix with payment subtable rows."""
    TAGS = {'table', 'thead', 'tbody', 'tfoot', 'tr', 'td', 'th'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        if tag in self.TAGS:
            node = Node(tag, attrs)
            self.stack[-1].children.append(node)
            self.stack.append(node)
        elif tag == 'br':
            self.stack[-1].children.append('\n')

    def handle_endtag(self, tag):
        if tag in self.TAGS:
            if self.stack[-1].tag != tag:
                raise ValueError('납입내역 표 구조를 확인해 주세요.')
            self.stack.pop()

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def cells(row):
    return [c for c in row.children if isinstance(c, Node) and c.tag in ('td', 'th')]


def clean(node):
    return ' '.join(node.text().split())


def date(value):
    if not re.fullmatch(r'\d{4}\.\d{2}\.\d{2}', value):
        raise ValueError('날짜 형식을 확인해 주세요.')
    return datetime.strptime(value, '%Y.%m.%d').date().isoformat()


def number(value):
    value = value.replace(',', '')
    if not re.fullmatch(r'-?\d+(?:\.\d+)?', value):
        raise ValueError('금액 또는 금리 형식을 확인해 주세요.')
    return value


TABLE_HEADERS = ['대출명(상환방법)', '대출일', '만기일', '대출금', '현잔고', '금리',
                 '납입일', '납입기간', '총납입금액', '원금상환금액']
HEADERS = ['고객명', '고객번호', '차기납입일', '대출명', '상환방법', '대출일', '만기일',
           '대출금', '현잔고', '금리', '납입일', '납입기간시작', '납입기간종료',
           '총납입금액', '원금상환금액']


def extract_transactions(html):
    parser = TableParser()
    parser.feed(html)
    parser.close()
    if len(parser.stack) != 1:
        raise ValueError('납입내역 표가 완전하지 않습니다.')
    tables = list(parser.root.find('table'))
    customers = [t for t in tables if t.attrs.get('summary', '').startswith('고객명, 고객번호, 차기납입일')]
    if len(customers) != 1:
        raise ValueError('고객정보 표를 찾지 못했습니다.')
    customer = [clean(c) for r in customers[0].find('tr') for c in cells(r)]
    if len(customer) != 6 or customer[::2] != HEADERS[:3]:
        raise ValueError('고객정보 표 형식이 변경되었습니다.')
    common = [customer[1], customer[3], date(customer[5])]
    records = []
    for table in tables:
        if not table.attrs.get('summary', '').startswith('대출명,'):
            continue
        labels = [re.sub(r'\s+', '', clean(c)) for c in table.find('th')]
        if labels != TABLE_HEADERS:
            raise ValueError('대출내역의 열 구성이 변경되었습니다.')
        bodies = [c for c in table.children if isinstance(c, Node) and c.tag == 'tbody']
        if len(bodies) != 1:
            raise ValueError('대출내역 표 형식이 변경되었습니다.')
        rows = [c for c in bodies[0].children if isinstance(c, Node) and c.tag == 'tr']
        for row in rows:
            outer = cells(row)
            if len(outer) != 7:
                raise ValueError('대출내역의 열 구성이 변경되었습니다.')
            name = re.fullmatch(r'(.+)\s+\(([^()]*)\)', clean(outer[0]))
            if not name:
                raise ValueError('대출명과 상환방법을 구분하지 못했습니다.')
            loan = [name[1], name[2], date(clean(outer[1])), date(clean(outer[2]))]
            loan += [number(clean(c)) for c in outer[3:6]]
            nested = list(outer[6].find('table'))
            if len(nested) != 1:
                raise ValueError('납입 상세 표 형식이 변경되었습니다.')
            payments = [cells(r) for r in nested[0].find('tr')]
            if not payments or len(payments) % 2:
                raise ValueError('납입 상세 행이 누락되었습니다.')
            for i in range(0, len(payments), 2):
                top, bottom = payments[i:i + 2]
                if len(top) != 3 or len(bottom) != 1 or any(c.attrs.get('rowspan') != '2' for c in top[:2]):
                    raise ValueError('납입 상세 행 형식이 변경되었습니다.')
                period = re.fullmatch(r'(\d{4}\.\d{2}\.\d{2})\s*~\s*(\d{4}\.\d{2}\.\d{2})', clean(top[1]))
                if not period:
                    raise ValueError('납입기간 형식을 확인해 주세요.')
                values = common + loan + [date(clean(top[0])), date(period[1]), date(period[2]),
                                          number(clean(top[2])), number(clean(bottom[0]))]
                records.append(dict(zip(HEADERS, values)))
    if not records:
        raise ValueError('지원하는 대출 납입내역을 찾지 못했습니다.')
    return HEADERS, records


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', nargs='?', type=Path, default=ROOT_DIR / 'input')
    parser.add_argument('--output-dir', type=Path, default=ROOT_DIR / 'output')
    parser.add_argument('--password-file', type=Path, default=ROOT_DIR / 'SamsungLife_password.txt')
    args = parser.parse_args(argv)
    try:
        sources = sorted(p for p in args.folder.expanduser().iterdir() if matches(p))
        if not sources:
            print('SamsungLife로 시작하는 HTML 파일이 없습니다.')
            return 0
        password = read_password(args.password_file.expanduser())
        output = args.output_dir.expanduser()
        output.mkdir(parents=True, exist_ok=True)
    except (OSError, ValueError):
        print('설정 오류: 입력 폴더와 암호 파일을 확인하세요.', file=sys.stderr)
        return 1
    succeeded = failed = 0
    for source in sources:
        try:
            headers, records = extract_transactions(decrypt_html(source, password))
            due_date = datetime.strptime(records[0]['차기납입일'], '%Y-%m-%d').strftime('%Y%m%d')
            stem = f'SamsungLife_{due_date}'
            sequence = 0
            while True:
                suffix = f'_{sequence}' if sequence else ''
                destination = output / f'{stem}{suffix}.csv'
                if os.path.lexists(destination):
                    sequence += 1
                    continue
                try:
                    write_csv(destination, headers, records)
                    break
                except FileExistsError:
                    # Another process may have created the name after our check.
                    sequence += 1
            print(f'완료: {destination.name} ({len(records)}건)')
            succeeded += 1
        except Exception as error:
            # Never expose passwords, plaintext, or third-party exception data.
            reason = str(error) if type(error) is ValueError and str(error).endswith('다.') else type(error).__name__
            print(f'실패: {source.name} ({reason})', file=sys.stderr)
            failed += 1
    print(f'처리 결과: 성공 {succeeded}개 / 실패 {failed}개')
    return 1 if failed else 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print('\n처리가 취소되었습니다.', file=sys.stderr)
        sys.exit(130)
