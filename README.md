# Batch PDF OCR Converter

A folder-based batch program that converts many PDFs to PNG, runs three
Tesseract OCR profiles, and cross-checks them into verified JSON files. A
FastAPI web interface remains available for occasional manual uploads.

The core output rule is:

```text
1 PDF -> multiple PNG images -> 3 candidate JSON files + 1 verified JSON file
```

The batch output is grouped by PDF:

```text
input/
  week1.pdf
  week2.pdf

batch_outputs/
  batch-summary.json
  week1/
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

## Requirements

- Python 3.10 or newer
- Tesseract OCR

PyMuPDF performs PDF rendering, so Poppler is not required.

### Install Tesseract

Ubuntu/Debian:

```bash
sudo apt update
sudo apt install tesseract-ocr
```

Install the Korean language pack for the default `kor+eng` OCR setting:

```bash
sudo apt install tesseract-ocr-kor
```

The program uses `kor+eng` by default. To use another installed Tesseract
language, pass `--language` to the batch command or set `OCR_LANGUAGE`:

```bash
python -m app.batch --language eng
```

macOS with Homebrew:

```bash
brew install tesseract
```

Windows: install Tesseract from the
[UB Mannheim builds](https://github.com/UB-Mannheim/tesseract/wiki), then add
the Tesseract installation directory to `PATH`.

Verify the installation:

```bash
tesseract --version
```

## Installation

Create and activate a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
```

On Windows:

```powershell
.venv\Scripts\activate
```

Install Python dependencies:

```bash
pip install -r requirements.txt
```

## Batch processing

1. Put all PDF files in `input/`.
2. Run:

```bash
python -m app.batch
```

Results are written to `batch_outputs/<pdf-name>/`. A `batch-summary.json`
file records completed, skipped, and failed PDFs.

Completed PDFs are skipped only when the source SHA-256, OCR settings,
pipeline version, and every expected output file still match. Replacing a PDF
under the same filename or deleting one output automatically triggers
reprocessing. Use `--overwrite` to force processing:

```bash
python -m app.batch --overwrite
```

Useful options:

```bash
# Process PDFs from another folder
python -m app.batch /path/to/pdfs --output-dir /path/to/results

# Include nested folders
python -m app.batch input --recursive

# Control concurrent PDF processing
python -m app.batch input --workers 2
```

The default is up to two concurrent PDFs. Each PDF already runs three OCR
passes per page, so raising `--workers` too high can reduce performance or
exhaust memory.

## Web interface

For occasional manual uploads:

```bash
uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000>. Web uploads retain the 50 MB per-file limit and
write their results to `outputs/`.

## OCR cross-checking

The three candidates use different page segmentation and image preprocessing:

- `balanced`: original image with automatic page segmentation
- `uniform-block`: high-contrast image treated as one text block
- `sparse-text`: sharpened image with sparse text detection

For each page, the verifier selects the candidate with the best combined
score: 40% similarity to the other candidates, 50% Tesseract word confidence,
and 10% exact-match support. The confidence weight prevents two noisy,
over-detected candidates from outvoting one clean result. Selecting one
complete candidate avoids corrupting sentences by mixing individual
characters from differently aligned OCR results.

Running three OCR passes takes roughly three times longer than a single pass.
`verified` means the best candidate was selected heuristically; it is not a
guarantee that every character is correct.

## Verified JSON format

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

If one OCR profile fails, its candidate contains an empty `text` value and the
verifier uses the remaining candidates. The result page also displays a
warning. Each profile has a 30-second per-page timeout.

Pages with no text, OCR confidence below 60, or candidate agreement below 0.5
are marked `review_required`. See
[`docs/user-flow-personas.md`](docs/user-flow-personas.md) for the reviewed
user flows and failure behavior.
