# Changelog

All notable changes to this project are documented here.

## 1.0.0 - 2026-02-26

- Added an interactive setup wizard (`uv run euraker`) with guided defaults.
- Added fast parallel downloading using authenticated request workers.
- Added dataset export after scraping with default `parquet` output.
- Added robust metadata extraction from Eureka's embedded `documentText` payload.
- Added configurable export destination (`--export-dir`, default `~/Downloads`).
- Added automatic temporary file cleanup after successful export.
- Added improved resume handling, CLI options, and user-facing documentation.
