#!/usr/bin/env python3
"""저장된 암호로 KT 이메일 명세서 PDF를 일괄 복호화합니다."""

import argparse
import getpass
import os
from pathlib import Path
import sys
import tempfile
import unicodedata

ROOT_DIR = Path(__file__).resolve().parent


def matches(path):
    name = unicodedata.normalize("NFC", path.name)
    return path.is_file() and path.suffix.lower() == ".pdf" and "KT email 명세서" in name


def output_filename(source):
    stem = unicodedata.normalize("NFC", source.stem)
    for colon in ("：", ":"):
        suffix = f"(문서열기암호{colon}주민번호 앞 6자리)"
        if stem.endswith(suffix):
            stem = stem[:-len(suffix)].rstrip()
            break
    return stem + source.suffix


def save_password(path):
    password = getpass.getpass("PDF 암호 (화면에 표시되지 않음): ")
    if not password or "\n" in password or "\r" in password:
        raise ValueError("암호는 비어 있지 않은 한 줄이어야 합니다.")
    if password != getpass.getpass("암호 다시 입력: "):
        raise ValueError("입력한 암호가 서로 다릅니다.")
    # 빈 준비 파일은 사용할 수 있지만, 저장된 암호는 덮어쓰지 않습니다.
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(fd, "r+", encoding="utf-8") as stream:
        if stream.read():
            raise FileExistsError("암호 파일에 이미 내용이 있습니다.")
        os.fchmod(stream.fileno(), 0o600)
        stream.write(password + "\n")


def read_password(path):
    # 앞자리 0과 공백은 암호의 일부이므로 보존합니다.
    password = path.read_text(encoding="utf-8-sig").rstrip("\r\n")
    if not password or "\n" in password or "\r" in password:
        raise ValueError("암호 파일에는 암호 하나를 한 줄로 저장해 주세요.")
    return password


def decrypt_one(source, destination, password):
    from pypdf import PdfReader, PdfWriter

    temporary = None
    try:
        with source.open("rb") as stream:
            reader = PdfReader(stream)
            if reader.is_encrypted and not reader.decrypt(password):
                raise ValueError("암호가 일치하지 않습니다.")
            page_count = len(reader.pages)
            writer = PdfWriter(clone_from=reader)
            with tempfile.NamedTemporaryFile(
                dir=destination.parent, prefix=".kt-", suffix=".tmp", delete=False
            ) as output:
                temporary = Path(output.name)
                writer.write(output)
            writer.close()

        with temporary.open("rb") as output:
            verified = PdfReader(output)
            if verified.is_encrypted or len(verified.pages) != page_count:
                raise ValueError("출력 PDF 검증에 실패했습니다.")

        # 검증이 끝난 파일만 공개하며, 실행 도중 생긴 기존 파일도 덮어쓰지 않습니다.
        os.link(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", nargs="?", type=Path, default=ROOT_DIR / "input",
                        help="PDF가 있는 폴더 (기본: 프로그램 루트/input, 하위 폴더 제외)")
    parser.add_argument("--password-file", type=Path,
                        help="UTF-8 암호 파일 (기본: 프로그램 루트/kt_password.txt)")
    parser.add_argument("--output-dir", type=Path,
                        help="저장 폴더 (기본: 프로그램 루트/output)")
    parser.add_argument("--save-password", action="store_true",
                        help="암호를 입력받아 비어 있거나 새로운 암호 파일에 저장하고 종료")
    args = parser.parse_args(argv)
    folder = args.folder.expanduser().resolve()
    password_file = (args.password_file.expanduser() if args.password_file
                     else ROOT_DIR / "kt_password.txt")
    output_dir = (args.output_dir.expanduser() if args.output_dir
                  else ROOT_DIR / "output")

    try:
        if not folder.is_dir():
            raise ValueError("대상 폴더가 존재하지 않습니다.")
        if args.save_password:
            save_password(password_file)
            print(f"암호 저장 완료: {password_file}")
            return 0

        sources = sorted(path for path in folder.iterdir() if matches(path))
        if not sources:
            print("파일명에 'KT email 명세서'가 포함된 PDF가 없습니다.")
            return 0
        try:
            import pypdf  # noqa: F401
        except ImportError:
            print("필수 패키지를 설치해 주세요: python3 -m pip install -r requirements.txt",
                  file=sys.stderr)
            return 1
        password = read_password(password_file)
        output_dir.mkdir(parents=True, exist_ok=True)
    except FileExistsError:
        print("암호 파일이 이미 있습니다. 기존 파일을 사용하거나 다른 경로를 지정해 주세요.",
              file=sys.stderr)
        return 1
    except FileNotFoundError:
        print("암호 파일 또는 저장 폴더가 없습니다. --save-password로 암호를 저장하거나 "
              "--password-file로 기존 파일을 지정해 주세요.", file=sys.stderr)
        return 1
    except (OSError, ValueError) as error:
        print(f"설정 오류: {error}", file=sys.stderr)
        return 1

    succeeded = skipped = failed = 0
    for source in sources:
        destination = output_dir / output_filename(source)
        if os.path.lexists(destination):
            print(f"건너뜀 (이미 존재): {destination.name}")
            skipped += 1
            continue
        try:
            decrypt_one(source, destination, password)
            print(f"완료: {destination.name}")
            succeeded += 1
        except Exception as error:
            # 라이브러리 예외 메시지에 민감한 값이 포함될 가능성을 피합니다.
            reason = "암호 불일치 또는 PDF 검증 실패" if isinstance(error, ValueError) else type(error).__name__
            print(f"실패: {source.name} ({reason})", file=sys.stderr)
            failed += 1
    print(f"처리 결과: 성공 {succeeded}개 / 건너뜀 {skipped}개 / 실패 {failed}개")
    print(f"저장 폴더: {output_dir.resolve()}")
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError):
        print("\n입력이 취소되었습니다.", file=sys.stderr)
        sys.exit(130)
