#!/usr/bin/env python3
"""현대카드 보안 HTML의 카드 사용내역을 파일별 CSV로 저장합니다."""

import argparse
import base64
import csv
import getpass
import hashlib
import hmac
from datetime import datetime
from html import unescape
import os
from pathlib import Path
import re
import sys
import tempfile

from decrypt_kt_pdfs import read_password

ROOT_DIR = Path(__file__).resolve().parent


def matches(path):
    return (path.is_file() and path.name.lower().startswith("hyundaicard")
            and path.suffix.lower() in (".html", ".htm"))


def decrypt_html(source, password):
    """VestMail SEED-CBC: header(16), encrypted key check(16), UTF-8 HTML."""
    from cryptography.hazmat.decrepit.ciphers.algorithms import SEED
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, modes

    # The wrapper is EUC-KR; only ASCII ciphertext assignments are read.
    wrapper = source.read_bytes().decode("latin-1")
    chunks = re.findall(r'\bs\[(\d+)\]\s*=\s*[\'"]([A-Za-z0-9+/=\s]+)[\'"]', wrapper)
    if not chunks or [int(index) for index, _ in chunks] != list(range(len(chunks))):
        raise ValueError("지원하지 않는 보안 HTML 형식입니다.")
    digest = hashlib.sha256(password.encode("utf-8")).digest()
    iv, key = digest[:16], hashlib.sha256(digest).digest()[:16]
    parts = []
    for _, encoded in chunks:
        data = base64.b64decode(re.sub(r'\s+', '', encoded), validate=True)
        if len(data) < 48 or len(data) % 16:
            raise ValueError("암호화된 데이터가 손상되었습니다.")
        decryptor = Cipher(SEED(key), modes.CBC(iv)).decryptor()
        plain = decryptor.update(data[16:]) + decryptor.finalize()
        if not hmac.compare_digest(plain[:16], key):
            raise ValueError("암호가 일치하지 않습니다.")
        unpadder = padding.PKCS7(128).unpadder()
        parts.append((unpadder.update(plain) + unpadder.finalize())[16:])
    return b''.join(parts).decode("utf-8")


HEADERS = ["이용일", "사용자", "이용카드", "이용가맹점", "이용금액", "할부개월",
           "할부회차", "결제원금", "수수료(이자)", "결제후잔액", "적립할인율(%)",
           "예상적립할인", "정기결제", "결제방식코드"]
STRING = r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\""
VALUE = re.compile(r'\s*(?:gf_Convert2ByteChar2\(\s*(' + STRING + r')\s*\)|(' + STRING + r'))\s*')


def decode_string(literal):
    def escape(match):
        value = match.group(1)
        if value.startswith(('u', 'x')):
            return chr(int(value[1:], 16))
        return {'n': '\n', 'r': '\r', 't': '\t', 'b': '\b', 'f': '\f', 'v': '\v', '0': '\0'}.get(value, value)
    return re.sub(r'\\(u[0-9a-fA-F]{4}|x[0-9a-fA-F]{2}|.)', escape, literal[1:-1])


def display_chars(text):
    replacements = {8217: "'", 8221: '"', 12288: ' ', 65507: '~', 65509: '\\'}
    return ''.join(chr(ord(c) - 65248) if 65281 <= ord(c) <= 65374 and ord(c) != 65340
                   else replacements.get(ord(c), c) for c in text)


def extract_transactions(html):
    """Read the data used by both desktop/mobile views; never execute email JS."""
    entries = list(re.finditer(r'\barUseDesc\s*\[\s*loop\+\+\s*\]\s*=\s*new\s+UseDesc\(\s*loop\s*,', html))
    if not entries:
        raise ValueError("지원하는 카드 사용내역 데이터를 찾지 못했습니다.")
    records = []
    for entry in entries:
        pos, values = entry.end(), []
        for i in range(15):
            match = VALUE.match(html, pos)
            if match is None:
                raise ValueError("카드 사용내역의 데이터 형식이 변경되었습니다.")
            value = decode_string(match.group(1) or match.group(2))
            if match.group(1) is not None:
                value = display_chars(value)
            values.append(unescape(value).strip())
            pos = match.end()
            if i < 14:
                if html[pos:pos + 1] != ',':
                    raise ValueError("카드 사용내역의 열 개수가 올바르지 않습니다.")
                pos += 1
        if not re.match(r'\s*\)\s*;', html[pos:]):
            raise ValueError("카드 사용내역의 열 개수가 올바르지 않습니다.")
        date, _, _, shop = values[:4]
        if not date and re.search(r'(소계|합계)', shop):
            continue
        if date:
            if not re.fullmatch(r'\d{6}', date):
                raise ValueError("이용일 형식을 확인해 주세요.")
            # Modern card statements use YYMMDD, in the 2000s.
            values[0] = datetime.strptime('20' + date, '%Y%m%d').date().isoformat()
        for index in range(4, 12):
            values[index] = values[index].replace(',', '')
            if values[index] and not re.fullmatch(r'-?\d+(?:\.\d+)?', values[index]):
                raise ValueError("금액 또는 적립률 형식을 확인해 주세요.")
        # Internal classification code is not a displayed transaction field.
        values.pop(12)
        records.append(dict(zip(HEADERS, values)))
    return HEADERS, records


def write_csv(destination, headers, records):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8-sig", newline="",
                                         dir=destination.parent, prefix=".hyundaicard-",
                                         suffix=".tmp", delete=False) as output:
            temporary = Path(output.name)
            writer = csv.DictWriter(output, fieldnames=headers)
            writer.writeheader()
            writer.writerows(records)
        with temporary.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames != headers or list(reader) != [dict.fromkeys(headers, "") | r for r in records]:
                raise ValueError("CSV 저장 검증에 실패했습니다.")
        os.link(temporary, destination)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def save_password(path):
    password = getpass.getpass("현대카드 HTML 암호 (화면에 표시되지 않음): ")
    if not password or '\n' in password or '\r' in password:
        raise ValueError("암호는 비어 있지 않은 한 줄이어야 합니다.")
    if password != getpass.getpass("암호 다시 입력: "):
        raise ValueError("입력한 암호가 서로 다릅니다.")
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(fd, "r+", encoding="utf-8") as stream:
        if stream.read():
            raise FileExistsError("암호 파일에 이미 내용이 있습니다.")
        os.fchmod(stream.fileno(), 0o600)
        stream.write(password + '\n')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", nargs="?", type=Path, default=ROOT_DIR / "input")
    parser.add_argument("--output-dir", type=Path, default=ROOT_DIR / "output")
    parser.add_argument("--password-file", type=Path, default=ROOT_DIR / "hyundaicard_password.txt")
    parser.add_argument("--save-password", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.save_password:
            save_password(args.password_file.expanduser())
            print("현대카드 암호 저장 완료")
            return 0
        sources = sorted(p for p in args.folder.expanduser().iterdir() if matches(p))
        if not sources:
            print("hyundaicard로 시작하는 HTML 파일이 없습니다.")
            return 0
        password = read_password(args.password_file.expanduser())
        output = args.output_dir.expanduser()
        output.mkdir(parents=True, exist_ok=True)
    except (OSError, ValueError):
        print("설정 오류: 입력 폴더와 암호 파일을 확인하세요. 암호 저장: --save-password", file=sys.stderr)
        return 1
    succeeded = skipped = failed = 0
    for source in sources:
        destination = output / (source.stem + ".csv")
        if os.path.lexists(destination):
            print(f"건너뜀 (이미 존재): {destination.name}")
            skipped += 1
            continue
        try:
            headers, records = extract_transactions(decrypt_html(source, password))
            write_csv(destination, headers, records)
            print(f"완료: {destination.name} ({len(records)}건)")
            succeeded += 1
        except Exception as error:
            # Never print third-party exception data, plaintext, or passwords.
            reason = str(error) if type(error) is ValueError and str(error).endswith('다.') else type(error).__name__
            print(f"실패: {source.name} ({reason})", file=sys.stderr)
            failed += 1
    print(f"처리 결과: 성공 {succeeded}개 / 건너뜀 {skipped}개 / 실패 {failed}개")
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError):
        print("\n입력이 취소되었습니다.", file=sys.stderr)
        sys.exit(130)
