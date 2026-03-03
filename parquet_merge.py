import argparse
import re
from pathlib import Path

import pandas as pd


def extract_date_window_key(path: Path):
    """Return sortable key from names like articles_dataset_YYYY-MM-DD_YYYY-MM-DD.parquet."""
    match = re.search(
        r"articles_dataset_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})\.parquet$",
        path.name,
    )
    if not match:
        return None
    return match.group(1), match.group(2)


def ordered_parquet_files(input_dir: Path, pattern: str):
    files = [p for p in input_dir.glob(pattern) if p.is_file()]
    if not files:
        return []

    with_key = []
    without_key = []
    for path in files:
        key = extract_date_window_key(path)
        if key is None:
            without_key.append(path)
        else:
            with_key.append((key, path))

    with_key.sort(key=lambda item: (item[0][0], item[0][1], item[1].name.lower()))
    without_key.sort(key=lambda p: p.name.lower())
    return [p for _, p in with_key] + without_key


def build_parser():
    parser = argparse.ArgumentParser(
        prog="parquet_merge.py",
        description="Merge multiple parquet datasets into one file in date-window order.",
    )
    parser.add_argument(
        "--input-dir",
        type=str,
        default="~/Downloads",
        help="Directory containing parquet files (default: ~/Downloads)",
    )
    parser.add_argument(
        "--pattern",
        type=str,
        default="articles_dataset_*.parquet",
        help="Filename pattern to include (default: articles_dataset_*.parquet)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="~/Downloads/articles_dataset_merged.parquet",
        help="Path to merged parquet output",
    )
    parser.add_argument(
        "--add-source",
        action="store_true",
        help="Add source_file and source_order columns to merged output",
    )
    return parser


def main():
    args = build_parser().parse_args()
    input_dir = Path(args.input_dir).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()

    files = ordered_parquet_files(input_dir, args.pattern)
    if not files:
        raise SystemExit(
            f"No parquet files matched pattern '{args.pattern}' in {input_dir}"
        )

    print(f"Found {len(files)} parquet files")
    for idx, file_path in enumerate(files, start=1):
        print(f"{idx:02d}. {file_path.name}")

    dataframes = []
    for idx, file_path in enumerate(files, start=1):
        df = pd.read_parquet(file_path)
        if args.add_source:
            df = df.copy()
            df["source_file"] = file_path.name
            df["source_order"] = idx
        dataframes.append(df)

    merged = pd.concat(dataframes, ignore_index=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    merged.to_parquet(output_path, index=False)

    print(f"Merged {len(files)} files into: {output_path}")
    print(f"Total rows: {len(merged)}")


if __name__ == "__main__":
    main()
