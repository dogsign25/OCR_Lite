# PDF OCR Converter

A lightweight FastAPI website that converts every page of an uploaded PDF to
PNG, runs Tesseract OCR on each page, and combines all page text into one JSON
file per PDF.

The core output rule is:

```text
1 PDF -> multiple PNG images -> 1 JSON file
```

For example:

```text
week1.pdf
  -> outputs/images/week1(1).png
  -> outputs/images/week1(2).png
  -> outputs/images/week1(3).png
  -> outputs/json/week1.json
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

Optional language packs can be installed separately. For example, Korean:

```bash
sudo apt install tesseract-ocr-kor
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

## Run

From the project root:

```bash
uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000> in a browser.

## Usage

1. Select or drag in one or more PDF files.
2. Click **Convert and run OCR**.
3. Download the combined JSON file and, optionally, individual PNG pages.

Uploads are stored in `uploads/`. PNG files are stored in `outputs/images/`,
and JSON files are stored in `outputs/json/`. The upload limit is 50 MB per
file.

When a name already exists, the app adds a short unique suffix, such as
`week1_a1b2c3d4.json`, to avoid overwriting previous results.

## JSON format

```json
{
  "source_pdf": "week1.pdf",
  "total_pages": 2,
  "pages": [
    {
      "page_number": 1,
      "image_file": "week1(1).png",
      "text": "OCR text from page 1"
    },
    {
      "page_number": 2,
      "image_file": "week1(2).png",
      "text": "OCR text from page 2"
    }
  ]
}
```

If OCR fails for an individual page, the page remains in the JSON with an
empty `text` value, and the result page displays a warning. This allows other
pages and other uploaded PDFs to finish processing. Each page also has a
30-second OCR timeout so a stalled OCR process cannot block the request
indefinitely.
