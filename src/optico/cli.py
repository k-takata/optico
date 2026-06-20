from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path

from .ico import extract_icon_pngs, optimize_pngs, rebuild_ico_from_pngs


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(
        prog="optico",
        description="Extract PNG and 32bpp bitmap frames from an ICO file, optimize them, and rebuild the ICO.",
    )
    parser.add_argument("ico_path", type=Path, help="Input .ico file")
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Directory to write extracted PNG files to. Defaults to <stem>_frames next to the input file.",
    )
    parser.add_argument(
        "--rebuild",
        type=Path,
        help="Path to write the rebuilt .ico file. Defaults to <stem>.optimized.ico next to the input file.",
    )
    parser.add_argument(
        "--optipng",
        default="optipng",
        help="optipng command to run for PNG optimization.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    ico_path: Path = args.ico_path
    if not ico_path.is_file():
        parser.error(f"input file does not exist: {ico_path}")

    output_dir = args.output_dir or ico_path.with_name(f"{ico_path.stem}_frames")
    rebuild_path = args.rebuild or ico_path.with_name(f"{ico_path.stem}.optimized.ico")

    result = extract_icon_pngs(ico_path, output_dir)
    if not result.extracted_frames:
        parser.error("no PNG or 32bpp bitmap frames were found")

    if result.skipped_frames:
        for message in result.skipped_frames:
            print(f"skip: {message}")

    optimize_pngs([frame.file_path for frame in result.extracted_frames if frame.optimizable], args.optipng)
    rebuild_ico_from_pngs(result.extracted_frames, rebuild_path)

    print(f"extracted {len(result.extracted_frames)} frame(s) to {output_dir}")
    print(f"rebuilt ICO: {rebuild_path}")
    return 0
