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
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print per-frame details during extraction.",
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
    original_size = ico_path.stat().st_size

    result = extract_icon_pngs(ico_path, output_dir)
    if not result.extracted_frames:
        parser.error("no PNG or 32bpp bitmap frames were found")

    if args.verbose:
        for frame in result.extracted_frames:
            print(
                "frame "
                f"{frame.index}: "
                f"{frame.source_kind} "
                f"{frame.width}x{frame.height} "
                f"bit_count={frame.bit_count} "
                f"planes={frame.planes} "
                f"color_count={frame.color_count} "
                f"optimizable={frame.optimizable} "
                f"path={frame.file_path}"
            )

    if result.skipped_frames:
        for message in result.skipped_frames:
            print(f"skip: {message}")

    optimize_pngs(
        [frame.file_path for frame in result.extracted_frames if frame.optimizable],
        args.optipng,
    )
    rebuild_ico_from_pngs(result.extracted_frames, rebuild_path)
    rebuilt_size = rebuild_path.stat().st_size
    saved_bytes = original_size - rebuilt_size

    print(f"extracted {len(result.extracted_frames)} frame(s) to {output_dir}")
    print(f"rebuilt ICO: {rebuild_path}")
    if saved_bytes >= 0:
        saved_percent = (saved_bytes / original_size * 100.0) if original_size else 0.0
        print(
            f"size: {original_size} -> {rebuilt_size} bytes "
            f"(reduced {saved_bytes} bytes, {saved_percent:.2f}%)"
        )
    else:
        increased_bytes = -saved_bytes
        increased_percent = (
            (increased_bytes / original_size * 100.0) if original_size else 0.0
        )
        print(
            f"size: {original_size} -> {rebuilt_size} bytes "
            f"(increased {increased_bytes} bytes, {increased_percent:.2f}%)"
        )
    return 0
