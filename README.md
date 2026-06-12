# 일괄 PDF OCR 변환기

여러 PDF를 폴더 단위로 PNG로 변환하고, 세 가지 Tesseract OCR 프로필을
실행한 뒤 결과를 교차 검증하여 검증된 JSON 파일을 생성하는 프로그램입니다.
필요할 때 파일을 직접 업로드할 수 있도록 FastAPI 웹 인터페이스도 제공합니다.

핵심 출력 규칙은 다음과 같습니다.

```text
PDF 1개 -> 여러 PNG 이미지
         -> 후보 JSON 파일 3개 + 검증된 JSON 파일 1개
         -> 검색 가능한 PDF 1개
         -> 전체 결과 ZIP 1개
```

일괄 처리 결과는 PDF별로 분류됩니다.

```text
input/
  week1.pdf
  week2.pdf

batch_outputs/
  batch-summary.json
  week1/
    week1.searchable.pdf
    week1.filtered.pdf
    week1.results.zip
    images/
      week1(1).png
      week1(2).png
    json/
      week1.candidate-1-balanced.json
      week1.candidate-2-uniform-block.json
      week1.candidate-3-sparse-text.json
      week1.verified.json
  week2/
    images/
    json/
```

## 요구 사항

- Python 3.10 이상
- Tesseract OCR

PDF 렌더링에는 PyMuPDF를 사용하므로 Poppler는 필요하지 않습니다.

### Tesseract 설치

Ubuntu/Debian:

```bash
sudo apt update
sudo apt install tesseract-ocr
```

기본 OCR 설정인 `kor+eng`를 사용하려면 한국어 언어 팩을 설치합니다.

```bash
sudo apt install tesseract-ocr-kor
```

프로그램은 기본적으로 `kor+eng`를 사용합니다. 설치된 다른 Tesseract 언어를
사용하려면 일괄 처리 명령에 `--language` 옵션을 전달하거나 `OCR_LANGUAGE`
환경 변수를 설정합니다.

```bash
python -m app.batch --language eng
```

Homebrew를 사용하는 macOS:

```bash
brew install tesseract
```

Windows에서는 [UB Mannheim 빌드](https://github.com/UB-Mannheim/tesseract/wiki)에서
Tesseract를 설치한 뒤 설치 디렉터리를 `PATH`에 추가합니다.

설치 여부를 확인합니다.

```bash
tesseract --version
```

## 설치

가상 환경을 생성하고 활성화합니다.

```bash
python -m venv .venv
source .venv/bin/activate
```

Windows:

```powershell
.venv\Scripts\activate
```

Python 의존성을 설치합니다.

```bash
pip install -r requirements.txt
```

## 일괄 처리

1. 모든 PDF 파일을 `input/`에 넣습니다.
2. 다음 명령을 실행합니다.

```bash
python -m app.batch
```

결과는 `batch_outputs/<pdf-name>/`에 저장됩니다. `batch-summary.json`에는
처리 완료, 건너뜀, 실패한 PDF가 기록됩니다.

각 PDF에는 OCR 텍스트를 보이지 않는 레이어로 삽입한
`<pdf-name>.searchable.pdf`가 생성됩니다. PDF 뷰어에서 단어 검색과 텍스트
복사가 가능하며, 필터를 사용한 경우 보존된 페이지만 포함합니다.
PNG, JSON, 필터 PDF, 검색 PDF는 `<pdf-name>.results.zip`으로도 묶입니다.

원본 SHA-256, OCR 설정, 파이프라인 버전과 예상된 모든 출력 파일이 기존
처리 결과와 일치할 때만 완료된 PDF를 건너뜁니다. 같은 파일명의 PDF를
교체하거나 출력 파일 중 하나를 삭제하면 자동으로 다시 처리합니다.
결과 ZIP의 구조와 CRC도 확인합니다. 재처리가 실패하면 부분 파일을 제거하고
마지막 정상 결과를 복구합니다.
강제로 처리하려면 `--overwrite` 옵션을 사용합니다.

```bash
python -m app.batch --overwrite
```

유용한 옵션:

```bash
# 다른 폴더의 PDF 처리
python -m app.batch /path/to/pdfs --output-dir /path/to/results

# 하위 폴더 포함
python -m app.batch input --recursive

# 동시에 처리할 PDF 수 지정
python -m app.batch input --workers 2
```

기본적으로 PDF를 최대 2개까지 동시에 처리합니다. 각 PDF의 페이지마다 이미
세 번의 OCR 작업이 실행되므로 `--workers` 값을 지나치게 높이면 성능이
저하되거나 메모리가 부족해질 수 있습니다.

입력 폴더와 출력 폴더를 같은 경로로 지정할 수 없습니다. 출력 폴더가 입력
폴더 아래에 있으면 재귀 검색에서 해당 하위 폴더를 자동 제외합니다.
대소문자만 다른 PDF 이름도 별도 결과 폴더에 저장됩니다.

### 단어 기반 페이지 필터

등록한 단어가 하나라도 포함된 페이지만 남기려면 `--filter-word`를 사용합니다.
기본 조건은 OR입니다.

```bash
python -m app.batch \
  --filter-word 계약서 \
  --filter-word "승인 완료"
```

모든 포함 단어가 있는 페이지만 남기려면 AND 조건을 사용합니다.

```bash
python -m app.batch \
  --filter-word 계약서 \
  --filter-word "승인 완료" \
  --filter-mode all
```

특정 단어가 있는 페이지는 제외할 수 있습니다. 제외 단어는 OR·AND 포함
조건보다 우선합니다.

```bash
python -m app.batch \
  --filter-word 계약서 \
  --exclude-word 초안 \
  --exclude-word 폐기
```

포함 단어 없이 제외 단어만 지정하면 해당 단어가 있는 페이지만 제거합니다.

```bash
python -m app.batch --exclude-word 기밀
```

필터는 세 OCR 후보 중 하나라도 등록 단어를 찾은 페이지를 보존합니다.
AND 조건에서는 세 후보 전체에서 찾은 포함 단어를 합산해 모두 일치하는지
판단합니다. 대소문자, 연속된 공백, 전각·반각 같은 Unicode 호환 문자 차이는
무시합니다. 결과는 각 PDF 출력 폴더의 `<pdf-name>.filtered.pdf`에 저장되며
원본 PDF는 수정하지 않습니다.
PNG와 JSON에도 보존된 페이지만 포함되고, 원래 페이지 번호는 유지됩니다.

조건을 만족하는 페이지가 하나도 없으면 빈 PDF를 만들지 않고 해당 파일을
실패로 기록합니다. OCR 결과를 기준으로 검색하므로 흐리거나 기울어진 문서에서는
단어를 놓칠 수 있습니다.

## 웹 인터페이스

필요할 때 파일을 직접 업로드하려면 다음 명령을 실행합니다.

```bash
uvicorn app.main:app --reload
```

<http://127.0.0.1:8000>을 엽니다. 웹 업로드는 요청당 최대 20개, 파일당
50MB로 제한하며 PDF당 최대 500페이지와 페이지당 최대 2,500만 렌더 픽셀을
허용합니다. 결과는 `outputs/`에 저장됩니다. 페이지 필터 입력란에는 단어를
쉼표 또는 줄바꿈으로 구분해 등록할 수 있고 포함·제외 단어 합계는 최대
100개입니다. OR·AND 포함 조건을 선택하고 제외 단어를 별도로 입력할 수
있으며, 결과 화면에서 필터링된 PDF를 내려받을 수 있습니다.

처리 중에는 현재 단계, 완료율, 예상 남은 시간이 표시됩니다. 여러 파일을
올리면 전체 파일 기준으로 진행률을 계산합니다. 서버를 재시작하면 진행 중인
작업 상태는 초기화됩니다.

### 필터 프리셋

포함 단어, OR·AND 조건, 제외 단어 조합에 이름을 붙여 저장할 수 있습니다.
프리셋은 서버가 아니라 현재 브라우저의 `localStorage`에 저장되므로 다른
브라우저나 장치에는 자동으로 공유되지 않습니다.

### OCR 결과 수정

웹 결과에서 `Review OCR text and page layout`을 펼치면 페이지별 OCR 텍스트를
직접 수정할 수 있습니다. `Show only pages needing review`를 선택하면 텍스트
없음, OCR 신뢰도 60 미만, 후보 일치도 0.5 미만인 페이지만 모아 볼 수
있습니다. `Save OCR corrections`를 누르면 verified JSON의 텍스트와 검수
상태가 갱신되고, 검색 가능한 PDF도 수정된 내용으로 다시 생성됩니다.

최초 OCR 텍스트와 수정 시각은 JSON에 보존됩니다. 수정 내용은 candidate
JSON과 원본 PDF에는 적용되지 않으며, 이미 확정된 페이지 필터 결과도 다시
계산하지 않습니다.

### 페이지 순서와 회전

검수 화면에서 페이지를 위·아래로 이동하거나 90도 단위로 회전한 뒤
`Apply page order and rotation`을 누릅니다. 다음 결과가 함께 갱신됩니다.

- `<이름>.edited.pdf`: 지정한 순서와 회전을 적용한 일반 PDF
- `<이름>.searchable.pdf`: 같은 배치와 현재 OCR 텍스트를 적용한 검색 PDF
- verified/candidate JSON: `output_page_number`, `rotation` 기록
- `<이름>.results.zip`: 최신 JSON, PNG, PDF를 다시 묶은 ZIP

`page_number`는 원본 PDF의 페이지 번호로 유지됩니다. 원본 PDF와 원본 PNG는
수정하지 않습니다.

같은 문서에 대한 OCR 수정과 페이지 편집은 문서별로 순차 처리됩니다. JSON,
PDF, ZIP 중 하나라도 갱신에 실패하면 수정 전 파일을 복구합니다.

### 결과 ZIP

웹 결과의 `Download all results as ZIP`에서 해당 문서의 PNG, 후보·검증 JSON,
필터 PDF, 편집 PDF, 검색 PDF를 한 번에 받을 수 있습니다. OCR 텍스트 또는
페이지 배치를 수정하면 ZIP도 즉시 다시 생성됩니다.

## OCR 교차 검증

세 후보는 서로 다른 페이지 분할 방식과 이미지 전처리를 사용합니다.

- `balanced`: 원본 이미지에 자동 페이지 분할 적용
- `uniform-block`: 고대비 이미지를 하나의 텍스트 블록으로 처리
- `sparse-text`: 선명도를 높인 이미지에서 흩어진 텍스트 감지

검증기는 각 페이지에서 종합 점수가 가장 높은 후보를 선택합니다. 점수는
다른 후보와의 유사도 40%, Tesseract 단어 신뢰도 50%, 완전 일치 지지도
10%로 계산합니다. 신뢰도에 가중치를 두어 노이즈가 많고 과도하게 감지된
두 후보가 정확한 하나의 결과보다 우선 선택되는 것을 방지합니다. 또한
완전한 후보 하나를 선택하므로 서로 다르게 정렬된 OCR 결과의 개별 문자를
섞어 문장이 손상되는 문제를 피할 수 있습니다.

OCR을 세 번 실행하므로 단일 실행보다 약 세 배의 시간이 걸립니다.
`verified`는 휴리스틱 방식으로 최적의 후보를 선택했다는 의미이며, 모든
문자가 정확하다는 보장은 아닙니다.

## 검증된 JSON 형식

```json
{
  "source_pdf": "week1.pdf",
  "total_pages": 2,
  "ocr_language": "kor+eng",
  "verification": {
    "candidate_count": 3,
    "method": "40% cross-candidate agreement + 50% OCR confidence + 10% exact-match support",
    "review_required_pages": 1
  },
  "pages": [
    {
      "page_number": 1,
      "image_file": "week1(1).png",
      "text": "OCR text from page 1",
      "confidence": 91.25,
      "selected_candidate": "balanced",
      "agreement_score": 0.9432,
      "selection_score": 0.9316,
      "review_required": false,
      "review_reasons": [],
      "output_page_number": 1,
      "rotation": 0
    },
    {
      "page_number": 2,
      "image_file": "week1(2).png",
      "text": "OCR text from page 2",
      "confidence": 58.74,
      "selected_candidate": "sparse-text",
      "agreement_score": 0.9015,
      "selection_score": 0.9035,
      "review_required": true,
      "review_reasons": ["low_ocr_confidence"]
    }
  ]
}
```

OCR 프로필 하나가 실패하면 해당 후보의 `text` 값은 비어 있으며, 검증기는
나머지 후보를 사용합니다. 결과 페이지에도 경고가 표시됩니다. 각 프로필의
페이지당 제한 시간은 30초입니다.

텍스트가 없거나 OCR 신뢰도가 60 미만이거나 후보 간 일치도가 0.5 미만인
페이지는 `review_required`로 표시됩니다. 검토된 사용자 흐름과 실패 동작은
[`docs/user-flow-personas.md`](docs/user-flow-personas.md)를 참고하세요.

## 보안 및 운영 주의

이 웹 앱은 인증 기능이 없는 로컬 도구입니다. 기본 주소인
`127.0.0.1`에서 사용하고 인터넷이나 공용 네트워크에 직접 공개하지 마세요.
`uploads/`와 `outputs/`에는 원본 문서와 OCR 텍스트가 암호화되지 않은 상태로
남으므로 민감 문서를 처리한 뒤에는 필요한 결과를 백업하고 해당 파일을
정리해야 합니다.

파일 개수·크기·페이지·렌더 픽셀 제한은 일반적인 자원 고갈을 줄이기 위한
방어입니다. 신뢰할 수 없는 사용자가 접근하는 서비스로 운영하려면 인증,
요청 전체 크기 제한, 작업 큐, 저장 기간 정책, 프로세스 격리를 추가해야 합니다.

## 테스트

전체 테스트를 실행합니다.

```bash
.venv/bin/python -m unittest discover -s tests -v
```

사용자 흐름 오류 검증은 `tests/test_user_flow_personas.py`에 있으며, 대량 처리
중 일부 실패, OCR 프로필 장애, 웹 입력 오류, 실패 산출물 정리, 필터 미일치
시 원본 보존, OCR 수정 후 검색 PDF 재생성을 확인합니다. 별도 서비스 테스트는
ZIP 내부 경로, 진행 상태, 페이지 순서·회전, 검색 PDF 회전을 검증합니다.
동시 수정 직렬화, 장애 시 산출물 롤백, PDF 자원 제한, 배치 출력 경로 충돌도
함께 검증합니다.

## 이후 개발 후보

- 필터 결과 썸네일 미리보기와 수동 페이지 선택
- OCR 영역 좌표 기반 텍스트 레이어 배치
- 작업 이력과 서버 계정별 프리셋 동기화
- 암호화 PDF 입력 지원
