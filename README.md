# Michigan Index of Authorities Generator

A desktop application that automatically generates a properly formatted **Index of Authorities** from Michigan appellate briefs.

## Features

- 📄 Accepts `.docx`, `.pdf`, or OCR `.zip` files
- ⚖️ Extracts all case citations, court rules, and statutes
- 📋 Displays a formatted Index of Authorities in your browser
- 💾 Exports a Word `.docx` with proper **dot-leader tab stops** (no manual formatting needed)
- 🔍 98%+ citation recall on Michigan appellate briefs

## Supported Citations

- **Cases** — Published and unpublished Michigan Court of Appeals opinions, Michigan Supreme Court, U.S. Supreme Court
- **Court Rules** — MCR citations (e.g., `MCR 3.965(C)(2)`)
- **Statutes** — MCL citations (e.g., `MCL 712A.13a(9)`)

## Download

| Platform | File |
|----------|------|
| Windows  | Build from source (see below) |
| Linux    | `dist/MichiganIndexGenerator_linux` |

> **Windows users:** Build from source using the instructions below, or run directly with Python.

## Running from Python (All Platforms)

### 1. Install dependencies

```bash
pip install pdfplumber python-docx docx2pdf
```

> `docx2pdf` requires Microsoft Word installed on Windows/Mac for DOCX→PDF conversion.
> PDF files can be processed directly without Word.

### 2. Run the app

```bash
python main.py
```

## Building a Windows .exe

On a Windows machine with Python installed:

```bash
pip install pyinstaller pdfplumber python-docx docx2pdf
pyinstaller michigan_index.spec
```

The `.exe` will be in `dist/MichiganIndexGenerator.exe`.

## Usage

1. Click **Browse** and select your brief (`.docx`, `.pdf`, or OCR `.zip`)
2. Click **Generate Index** — the app scans for all citations
3. Click **View in Browser** to review the formatted index
4. Click **Save as Word** to export a `.docx` with proper dot leaders

## How It Works

The app uses a custom citation parser (`CitationParser`) that:
- Detects Michigan case citation patterns (reporters, court abbreviations)
- Skips the existing Index of Authorities pages to avoid double-counting
- Resolves `Id.` references to the correct preceding case
- Reads the existing Index pages (if present) for full citation display text
- Scans the body for all page numbers where each citation appears

## Support This Tool

If this saves you time, please consider a small donation:

[💛 Donate via PayPal](https://www.paypal.com/donate/?hosted_button_id=4AM22J9AMNCEE)

## License

MIT License — free to use, modify, and distribute.

## Author

Built for Michigan appellate attorneys.
