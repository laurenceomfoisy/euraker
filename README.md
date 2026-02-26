# Euraker

Standalone scraper for collecting article HTML pages from Eureka after manual institutional login.

## What it does

- Opens Eureka in Chrome (prefers `undetected-chromedriver`, falls back to regular Selenium ChromeDriver)
- Pauses for manual login and manual search setup
- Extracts document keys from the results page
- Builds article URLs and downloads each article HTML to disk
- Supports resume logic through progress files

## Requirements

- Python 3.9+
- Google Chrome installed
- Access to Eureka through your institution

Install dependencies:

```bash
pip install -r requirements.txt
```

## Usage

```bash
python eureka_scraper.py --start-date 2024-01-01 --end-date 2024-01-31
```

Optional flags:

- `--output-dir` output folder root (default: `./eureka_articles`)
- `--start-index` start index for downloads
- `--resume` resume based on a saved progress file

## Notes

- The script intentionally requires manual login and search interaction.
- Downloaded files and screenshots are saved inside the chosen output directory.
