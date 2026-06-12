# 일괄 PDF OCR 변환기

여러 PDF를 폴더 단위로 PNG로 변환하고, 세 가지 Tesseract OCR 프로필을
실행한 뒤 결과를 교차 검증하여 검증된 JSON 파일을 생성하는 프로그램입니다.
필요할 때 파일을 직접 업로드할 수 있도록 FastAPI 웹 인터페이스도 제공합니다.

핵심 출력 규칙은 다음과 같습니다.

```text
PDF 1개 -> 여러 PNG 이미지 -> 후보 JSON 파일 3개 + 검증된 JSON 파일 1개
```

일괄 처리 결과는 PDF별로 분류됩니다.

```text
input/
  week1.pdf
  week2.pdf

batch_outputs/
  batch-summary.json
  week1/
    week1.filtered.pdf
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

원본 SHA-256, OCR 설정, 파이프라인 버전과 예상된 모든 출력 파일이 기존
처리 결과와 일치할 때만 완료된 PDF를 건너뜁니다. 같은 파일명의 PDF를
교체하거나 출력 파일 중 하나를 삭제하면 자동으로 다시 처리합니다.
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

### 단어 기반 페이지 필터

등록한 단어가 하나라도 포함된 페이지만 남기려면 `--filter-word`를 사용합니다.

```bash
python -m app.batch --filter-word 계약서
```

여러 단어를 등록하면 OR 조건으로 처리합니다. 다음 예시는 `계약서` 또는
`승인 완료`가 감지된 페이지만 남깁니다.

```bash
python -m app.batch \
  --filter-word 계약서 \
  --filter-word "승인 완료"
```

필터는 세 OCR 후보 중 하나라도 등록 단어를 찾은 페이지를 보존합니다.
대소문자와 연속된 공백 차이는 무시합니다. 결과는 각 PDF 출력 폴더의
`<pdf-name>.filtered.pdf`에 저장되며 원본 PDF는 수정하지 않습니다.
PNG와 JSON에도 보존된 페이지만 포함되고, 원래 페이지 번호는 유지됩니다.

등록 단어가 있는 페이지를 하나도 찾지 못하면 빈 PDF를 만들지 않고 해당
파일을 실패로 기록합니다. OCR 결과를 기준으로 검색하므로 흐리거나 기울어진
문서에서는 단어를 놓칠 수 있습니다.

## 웹 인터페이스

필요할 때 파일을 직접 업로드하려면 다음 명령을 실행합니다.

```bash
uvicorn app.main:app --reload
```

<http://127.0.0.1:8000>을 엽니다. 웹 업로드는 파일당 50MB 제한을 유지하며
결과는 `outputs/`에 저장됩니다. 페이지 필터 입력란에는 단어를 쉼표 또는
줄바꿈으로 구분해 등록할 수 있으며, 필터를 사용하면 결과 화면에서 필터링된
PDF를 내려받을 수 있습니다.

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
      "review_reasons": []
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

## 테스트

전체 테스트를 실행합니다.

```bash
.venv/bin/python -m unittest discover -s tests -v
```

사용자 흐름 오류 검증은 `tests/test_user_flow_personas.py`에 있으며, 대량 처리
중 일부 실패, OCR 프로필 장애, 웹 입력 오류, 실패 산출물 정리, 필터 미일치
시 원본 보존을 확인합니다.
