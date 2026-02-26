# Euraker

Euraker is a standalone, user-friendly scraper for downloading Eureka article pages after manual institutional login.

It is built for reliability: it saves progress during scraping, supports resume, and provides a simple CLI.
After each run, it exports a consolidated dataset (default: parquet) to `~/Downloads` and cleans temporary scrape files.

## Features

- Manual-login workflow compatible with institutional access (no credential storage)
- Robust document-key extraction with fallback methods
- Batch downloads with checkpointing (`progress.txt`)
- Resume support for interrupted runs (`--resume` + `--start-index`)
- Friendly CLI command: `euraker`

## Requirements

- Python 3.10-3.13
- Google Chrome installed
- Access to Eureka through your institution
- [`uv`](https://docs.astral.sh/uv/) for environment + dependency management

## Install (recommended: uv)

From the repository root:

```bash
uv sync --python 3.12
```

This creates a virtual environment and installs all dependencies from `pyproject.toml`.

## Run

Use the CLI entrypoint:

```bash
uv run euraker --start-date 2024-01-01 --end-date 2024-01-31
```

Guided setup (recommended for first-time users):

```bash
uv run euraker --interactive
```

Tip: running `uv run euraker` with no flags now launches the interactive wizard automatically.

Faster parallel mode (recommended for bigger downloads):

```bash
uv run euraker --start-date 2024-01-01 --end-date 2024-01-31 --mode requests --workers 8 --yes
```

Or run the module file directly:

```bash
uv run python eureka_scraper.py --start-date 2024-01-01 --end-date 2024-01-31
```

## User Flow

1. Script opens Eureka in Chrome.
2. You log in manually and execute your search.
3. You return to the terminal and press Enter.
4. Euraker extracts document keys and starts downloading article HTML files.
5. At the end, press Enter to close the browser.

## CLI Options

- `--start-date YYYY-MM-DD` start date for the search window
- `--end-date YYYY-MM-DD` end date for the search window
- `--output-dir PATH` root output directory (default: `./eureka_articles`)
- `--start-index N` start from a specific result index
- `--batch-size N` number of articles per batch (default: `1000`)
- `--resume` resume from saved `progress.txt` in the same date-range folder
- `--yes` skip large-download confirmation prompt
- `--mode {auto,selenium,requests}` choose downloader strategy
- `--workers N` number of parallel workers in requests mode
- `--interactive` launch guided setup wizard
- `--export-format {parquet,csv,jsonl}` dataset output format (default: `parquet`)
- `--export-dir PATH` final dataset destination (default: `~/Downloads`)

## Performance Tips

- Use `--mode requests --workers 6` to `--workers 10` for faster downloads.
- Keep `--mode selenium` only when requests mode has access issues.
- Use `--resume` after interruptions instead of restarting from zero.

### How many workers should I use?

- Start with `8` workers (good default on most laptops/desktops).
- Use `6` if you see occasional failures/timeouts.
- Try `10-12` only if downloads are stable and you want maximum speed.
- If unsure, run `--interactive` and accept the suggested value.

## Output Layout

During scraping, files are written to `--output-dir`. After export, temporary files are removed.

Default final output location:

```text
~/Downloads/articles_dataset_2024-01-01_2024-01-31.parquet
```

If you set a custom export folder:

```bash
uv run euraker --start-date 2024-01-01 --end-date 2024-01-31 --export-dir ~/data/euraker
```

Temporary working folder shape (before cleanup):

```text
eureka_articles/
  2024-01-01_2024-01-31/
    article_0001.html
    article_0002.html
    ...
    article_urls.csv
    doc_keys.json
    progress.txt
    *_screenshot.png
    *_error.txt
```

## Resume Examples

Resume from the last saved checkpoint:

```bash
uv run euraker --start-date 2024-01-01 --end-date 2024-01-31 --resume
```

Resume from a specific index:

```bash
uv run euraker --start-date 2024-01-01 --end-date 2024-01-31 --start-index 500
```

## Troubleshooting

- If login fails, verify institutional access is active in your browser session.
- If document keys are not found, ensure you are on the Eureka results page before pressing Enter.
- If Chrome startup fails, update Chrome and re-run `uv sync`.

## Security and Data Handling

- Euraker does not collect or store credentials.
- Authentication happens manually in your own browser window.
- Downloaded content is written only to your local output directory.

## Load in R

Parquet (recommended):

```r
library(arrow)
df <- read_parquet("~/Downloads/articles_dataset_2024-01-01_2024-01-31.parquet")
```

CSV:

```r
library(readr)
df <- read_csv("~/Downloads/articles_dataset_2024-01-01_2024-01-31.csv")
```
