#!/usr/bin/env python3
"""암호 없는 신한카드 HTML의 카드 사용내역을 파일별 CSV로 저장합니다."""

import argparse
from datetime import datetime
import os
from pathlib import Path
import re
import sys

from decrypt_shcard_html import CardTableParser
from decrypt_hyundaicard_html import write_csv

ROOT_DIR = Path(__file__).resolve().parent
HEADERS = ['이용일자', '이용카드', '이용가맹점', '이용원금', '수수료',
           '할인금액', '입금완납금액', '입금하실 금액', '캐시백', '포인트적립율(마이신한)']


def matches(path):
    return (path.is_file() and path.name.lower().startswith('shinhancard')
            and path.suffix.lower() in ('.html', '.htm'))


def read_html(source):
    data = source.read_bytes()
    # EUC-KR statements may use the CP949 extension. Never replace invalid bytes.
    for encoding in ('utf-8-sig', 'cp949'):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            pass
    raise ValueError('HTML 한글 인코딩을 확인해 주세요.')


def extract_transactions(html):
    parser = CardTableParser()
    parser.feed(html)
    parser.close()
    if parser.found != 1 or parser.depth:
        raise ValueError('지원하는 카드 사용내역 표를 찾지 못했습니다.')
    # Check the two-tier header so a changed statement cannot silently shift columns.
    labels = [re.sub(r'\s+', '', cell[2]) for section, row in parser.rows
              if section == 'thead' for cell in row]
    expected = ['이용일자', '이용카드', '이용가맹점', '이용금액', '입금하실금액',
                '캐시백', '포인트적립율(마이신한)', '이용원금', '수수료', '할인금액', '입금완납금액']
    if labels != expected:
        raise ValueError('사용내역의 제목 구성이 변경되었습니다.')
    records = []
    for section, row in parser.rows:
        if section == 'thead' or not row:
            continue
        if row[0][0] == 'th' and re.search(r'(소계|합계)', re.sub(r'\s+', '', row[0][2])):
            continue
        if len(row) != len(HEADERS) or any(
                attrs.get('colspan', '1') != '1' or attrs.get('rowspan', '1') != '1'
                for _, attrs, _ in row):
            raise ValueError('사용내역의 열 구성이 변경되었습니다.')
        values = [cell[2] for cell in row]
        if not re.fullmatch(r'\d{2}\.\d{2}\.\d{2}', values[0]):
            raise ValueError('이용일자 형식을 확인해 주세요.')
        values[0] = datetime.strptime('20' + values[0], '%Y.%m.%d').date().isoformat()
        for index in range(3, 9):
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
    args = parser.parse_args(argv)
    try:
        sources = sorted(p for p in args.folder.expanduser().iterdir() if matches(p))
        if not sources:
            print('shinhancard로 시작하는 HTML 파일이 없습니다.')
            return 0
        output = args.output_dir.expanduser()
        output.mkdir(parents=True, exist_ok=True)
    except OSError:
        print('설정 오류: 입력 및 출력 폴더를 확인하세요.', file=sys.stderr)
        return 1
    succeeded = skipped = failed = 0
    for source in sources:
        destination = output / (source.stem + '.csv')
        if os.path.lexists(destination):
            print(f'건너뜀 (이미 존재): {destination.name}')
            skipped += 1
            continue
        try:
            headers, records = extract_transactions(read_html(source))
            write_csv(destination, headers, records)
            print(f'완료: {destination.name} ({len(records)}건)')
            succeeded += 1
        except Exception as error:
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
