# KT 이메일 명세서 PDF 암호 해제

Python 3.9 이상에서 실행합니다. `input` 폴더 바로 아래에서 파일명에 `KT email 명세서`가 포함된 PDF를 찾아 저장된 암호로 해제합니다. 맥의 한글 분해형 파일명과 `.PDF` 확장자도 인식합니다.

기본 경로는 실행한 터미널 위치와 관계없이 프로그램 파일이 있는 루트 기준입니다.

```text
청구서 정리/
├── decrypt_kt_pdfs.py
├── kt_password.txt     # 암호 하나를 한 줄로 저장
├── input/              # 읽을 PDF
└── output/             # 암호가 해제된 PDF
```

## 설치 및 실행

mise가 설치되어 있으면, `kt_password.txt`에 암호를 저장하고 `input`에 PDF를 넣은 뒤 다음 명령으로 실행하세요.

```sh
mise run kt
```

Python 3.9 이상이 설치되어 있어야 합니다. 처음 실행할 때 `.venv`와 필요한 패키지를 자동으로 준비하므로 인터넷 연결이 필요합니다. 이후에는 준비된 환경을 재사용합니다. mise가 설정 신뢰를 요구하면 이 폴더에서 `mise trust`를 한 번 실행하세요.

프로그램 옵션도 전달할 수 있습니다.

```sh
mise run kt -- --save-password
mise run kt -- --help
```

작업 설정은 [mise 공식 작업 문서](https://mise.jdx.dev/tasks/toml-tasks.html)를 따릅니다.

### mise 없이 직접 실행

이 폴더에서 터미널을 열고 실행하세요.

```sh
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

`input`에 처리할 PDF를 넣고, 루트의 빈 `kt_password.txt`에 암호 하나를 한 줄로 입력해 저장하세요. 또는 다음 명령으로 저장할 수 있습니다. 입력은 화면에 표시되지 않습니다.

```sh
python3 decrypt_kt_pdfs.py --save-password
```

암호는 `kt_password.txt`에 평문으로 저장됩니다. macOS/Linux에서는 프로그램으로 저장 시 파일 소유자에게만 읽기·쓰기 권한을 부여합니다. 암호 파일을 공유하거나 버전 관리에 추가하지 마세요. 앞자리 0도 그대로 보존됩니다. `--save-password`는 비어 있는 파일에만 저장하며, 이미 내용이 있으면 덮어쓰지 않습니다.

PDF 암호 해제:

```sh
python3 decrypt_kt_pdfs.py
```

결과는 파일명 끝의 `(문서열기암호：주민번호 앞 6자리)`를 제거해 `output` 폴더에 저장됩니다. 예: `2026년 7월 KT email 명세서.pdf`. 한글 분해형 파일명과 일반 콜론(`:`)도 인식합니다. `input`의 원본 내용과 파일명은 보존되며, 정리된 출력 파일명이 이미 존재하면 건너뜁니다. 이전 실행에서 생성한 긴 이름의 출력 파일은 그대로 남습니다. 파일별로 실패해도 나머지는 계속 처리합니다. 모든 PDF에 같은 암호를 사용합니다.

이미 저장해 둔 암호 파일을 사용하려면 UTF-8 텍스트 파일에 암호 하나만 한 줄로 저장한 뒤 경로를 지정하세요.

```sh
python3 decrypt_kt_pdfs.py --password-file "/경로/저장된암호.txt"
```

다른 입력·출력 폴더 지정:

```sh
python3 decrypt_kt_pdfs.py "/경로/청구서" --password-file "/경로/저장된암호.txt" --output-dir "/경로/결과"
```

선택한 경로에 공백이 있으면 따옴표로 감싸세요. 상대 경로 옵션은 현재 터미널 폴더 기준입니다. 재실행 시에는 `source .venv/bin/activate`로 가상환경을 먼저 활성화하세요.

출력은 다시 열어 암호화 해제 여부와 페이지 수를 검증한 뒤 저장합니다. PDF 구조를 다시 저장하므로 기존 전자서명의 유효성은 보존되지 않을 수 있습니다.

참고: [pypdf 공식 암호 해제 문서](https://pypdf.readthedocs.io/en/stable/user/encryption-decryption.html)

## 현대카드 HTML → CSV

`input` 바로 아래의 `hyundaicard`로 시작하는 `.html`/`.htm` 파일을 처리합니다(대소문자 무관). 현대카드 암호는 루트의 `hyundaicard_password.txt`에 한 줄로 저장하세요. KT 암호와 별도로 관리하며, 앞자리 0도 보존합니다.

```sh
mise run hyundaicard
```

암호를 화면에 표시하지 않고 저장하려면:

```sh
mise run hyundaicard -- --save-password
```

기존 암호가 있으면 덮어쓰지 않습니다. 암호 파일은 평문이므로 공유하지 마세요. Git에서는 제외됩니다. `--save-password`로 저장하면 소유자만 읽고 쓸 수 있습니다.

mise 없이 실행하거나 경로를 지정할 수도 있습니다. 위의 설치 절차로 패키지를 준비한 뒤 실행하세요.

```sh
.venv/bin/python decrypt_hyundaicard_html.py
.venv/bin/python decrypt_hyundaicard_html.py "/경로/청구서" --password-file "/경로/암호.txt" --output-dir "/경로/결과"
```

예: `input/hyundaicard_20261001.html` → `output/hyundaicard_20261001.csv`

- 현재 명세서의 VestMail SEED-CBC 보안 형식을 지원합니다. 브라우저나 외부 접속 없이 복호화하고, HTML의 JavaScript를 실행하지 않고 결제상세내역 원본 데이터를 읽습니다.
- CSV에는 이용일, 사용자, 이용카드, 이용가맹점, 이용금액, 할부개월, 할부회차, 결제원금, 수수료(이자), 결제후잔액, 적립할인율(%), 예상적립할인, 정기결제, 결제방식코드가 포함됩니다. 정기결제는 원본의 Y/N, 결제방식코드는 원본 값을 보존합니다.
- 이용일은 `YYYY-MM-DD`, 금액은 천 단위 쉼표 없는 숫자로 저장합니다. UTF-8 BOM으로 저장해 Excel에서도 한글을 읽을 수 있습니다.
- 소계·총합계 행만 제외합니다. 동일하게 보이는 실제 거래, 취소·조정 행, 결제원금 0원 행도 보존하므로 명세서의 요약 건수와 CSV 행 수가 다를 수 있습니다. 해외 거래도 결제상세내역에 포함된 원화 금액으로 저장하며, 별도 해외 상세 표와 취소 안내 표는 중복 추가하지 않습니다.
- 원본 HTML은 그대로 두며 복호화한 HTML은 저장하지 않습니다. CSV가 이미 있으면 건너뜁니다. 다시 생성하려면 기존 CSV를 다른 곳으로 옮긴 뒤 실행하세요.
- 암호가 틀리거나 형식을 읽을 수 없는 파일은 실패로 표시하고 나머지 파일은 계속 처리합니다. 실패가 있으면 종료 코드는 1입니다.

검증 테스트:

```sh
.venv/bin/python -m unittest discover -s tests
```
