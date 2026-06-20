from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import struct
import subprocess
from typing import Sequence

from PIL import Image

ICONDIR_STRUCT = struct.Struct("<HHH")
ICONDIRENTRY_STRUCT = struct.Struct("<BBBBHHII")
BITMAPINFOHEADER_SIZE = 40
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
BI_RGB = 0
BI_BITFIELDS = 3


@dataclass(frozen=True)
class IconFrame:
    index: int
    width: int
    height: int
    source_kind: str
    file_path: Path
    optimizable: bool
    color_count: int
    planes: int
    bit_count: int


@dataclass(frozen=True)
class ExtractionResult:
    extracted_frames: list[IconFrame]
    skipped_frames: list[str]


@dataclass(frozen=True)
class _IconEntry:
    index: int
    width: int
    height: int
    color_count: int
    planes: int
    bit_count: int
    bytes_in_res: int
    image_offset: int
    payload: bytes


class IcoError(RuntimeError):
    pass


def extract_icon_pngs(ico_path: Path, output_dir: Path) -> ExtractionResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    entries = _read_ico_entries(ico_path)

    extracted_frames: list[IconFrame] = []
    skipped_frames: list[str] = []

    for entry in entries:
        try:
            (
                file_bytes,
                actual_width,
                actual_height,
                source_kind,
                file_extension,
                optimizable,
            ) = _entry_to_export(entry)
        except IcoError as exc:
            skipped_frames.append(f"frame {entry.index}: {exc}")
            continue

        if source_kind.startswith("bitmap") and source_kind != "bitmap32":
            color_count = entry.color_count
            planes = entry.planes
            bit_count = entry.bit_count
        else:
            color_count = 0
            planes = 1
            bit_count = 32

        output_name = (
            f"frame_{entry.index:02d}_{actual_width}x{actual_height}{file_extension}"
        )
        output_path = output_dir / output_name
        output_path.write_bytes(file_bytes)
        extracted_frames.append(
            IconFrame(
                index=entry.index,
                width=actual_width,
                height=actual_height,
                source_kind=source_kind,
                file_path=output_path,
                optimizable=optimizable,
                color_count=color_count,
                planes=planes,
                bit_count=bit_count,
            )
        )

    return ExtractionResult(
        extracted_frames=extracted_frames, skipped_frames=skipped_frames
    )


def optimize_pngs(png_paths: Sequence[Path], optipng_command: str) -> None:
    for png_path in png_paths:
        try:
            completed = subprocess.run(
                [optipng_command, "-quiet", "-nx", "-o7", str(png_path)],
                check=False,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError as exc:
            raise IcoError(f"optipng command not found: {optipng_command}") from exc
        if completed.returncode != 0:
            stderr = completed.stderr.strip()
            message = f"optipng failed for {png_path}"
            if stderr:
                message = f"{message}: {stderr}"
            raise IcoError(message)


def rebuild_ico_from_pngs(frames: Sequence[IconFrame], output_path: Path) -> None:
    frame_payloads: list[tuple[IconFrame, int, int, bytes]] = []
    for frame in frames:
        payload = frame.file_path.read_bytes()
        if frame.source_kind in {"png", "bitmap32"}:
            width, height = _png_dimensions(payload)
        else:
            width, height = frame.width, frame.height
        frame_payloads.append((frame, width, height, payload))

    output_path.parent.mkdir(parents=True, exist_ok=True)

    entry_count = len(frame_payloads)
    header = ICONDIR_STRUCT.pack(0, 1, entry_count)
    directory_size = ICONDIRENTRY_STRUCT.size * entry_count
    offset = ICONDIR_STRUCT.size + directory_size
    directory_entries = []
    payload_chunks = []

    for frame, width, height, payload in frame_payloads:
        directory_entries.append(
            ICONDIRENTRY_STRUCT.pack(
                0 if width >= 256 else width,
                0 if height >= 256 else height,
                frame.color_count,
                0,
                frame.planes,
                frame.bit_count,
                len(payload),
                offset,
            )
        )
        payload_chunks.append(payload)
        offset += len(payload)

    output_path.write_bytes(
        header + b"".join(directory_entries) + b"".join(payload_chunks)
    )


def _read_ico_entries(ico_path: Path) -> list[_IconEntry]:
    data = ico_path.read_bytes()
    if len(data) < ICONDIR_STRUCT.size:
        raise IcoError("file is too small to be an ICO file")

    reserved, image_type, image_count = ICONDIR_STRUCT.unpack_from(data, 0)
    if reserved != 0 or image_type != 1:
        raise IcoError("file does not look like an ICO file")

    entries: list[_IconEntry] = []
    directory_offset = ICONDIR_STRUCT.size
    for index in range(image_count):
        start = directory_offset + index * ICONDIRENTRY_STRUCT.size
        end = start + ICONDIRENTRY_STRUCT.size
        if end > len(data):
            raise IcoError("ICO directory is truncated")

        (
            width,
            height,
            color_count,
            reserved_byte,
            planes,
            bit_count,
            bytes_in_res,
            image_offset,
        ) = ICONDIRENTRY_STRUCT.unpack_from(data, start)

        if image_offset + bytes_in_res > len(data):
            raise IcoError(f"ICO image {index} is truncated")

        entries.append(
            _IconEntry(
                index=index,
                width=256 if width == 0 else width,
                height=256 if height == 0 else height,
                color_count=color_count,
                planes=planes,
                bit_count=bit_count,
                bytes_in_res=bytes_in_res,
                image_offset=image_offset,
                payload=data[image_offset : image_offset + bytes_in_res],
            )
        )

    return entries


def _entry_to_export(entry: _IconEntry) -> tuple[bytes, int, int, str, str, bool]:
    if entry.payload.startswith(PNG_SIGNATURE):
        width, height = _png_dimensions(entry.payload)
        return entry.payload, width, height, "png", ".png", True

    if entry.bit_count == 32:
        png_bytes, width, height = _bitmap_entry_to_png(entry.payload)
        return png_bytes, width, height, "bitmap32", ".png", True

    return (
        entry.payload,
        entry.width,
        entry.height,
        f"bitmap{entry.bit_count}",
        ".dib",
        False,
    )


def _bitmap_entry_to_png(payload: bytes) -> tuple[bytes, int, int]:
    if len(payload) < BITMAPINFOHEADER_SIZE:
        raise IcoError("bitmap payload is truncated")

    header_size = struct.unpack_from("<I", payload, 0)[0]
    if header_size < BITMAPINFOHEADER_SIZE or len(payload) < header_size:
        raise IcoError("unsupported bitmap header")

    width = struct.unpack_from("<i", payload, 4)[0]
    total_height = struct.unpack_from("<i", payload, 8)[0]
    planes = struct.unpack_from("<H", payload, 12)[0]
    bit_count = struct.unpack_from("<H", payload, 14)[0]
    compression = struct.unpack_from("<I", payload, 16)[0]

    if planes != 1 or bit_count != 32:
        raise IcoError(f"unsupported bitmap format ({bit_count} bpp)")
    if compression not in (BI_RGB, BI_BITFIELDS):
        raise IcoError(f"unsupported bitmap compression ({compression})")

    actual_height = abs(total_height) // 2
    if actual_height <= 0:
        raise IcoError("bitmap height is invalid")

    pixel_width = abs(width)
    if pixel_width <= 0:
        raise IcoError("bitmap width is invalid")

    mask_bytes = 0
    if header_size == BITMAPINFOHEADER_SIZE and compression == BI_BITFIELDS:
        mask_bytes = 12

    xor_stride = pixel_width * 4
    xor_size = xor_stride * actual_height
    xor_offset = header_size + mask_bytes
    xor_end = xor_offset + xor_size
    if xor_end > len(payload):
        raise IcoError("bitmap pixel data is truncated")

    rgba_image = _decode_bgra32_to_rgba(
        payload[xor_offset:xor_end],
        pixel_width,
        actual_height,
        bottom_up=total_height >= 0,
    )
    buffer = BytesIO()
    rgba_image.save(buffer, format="PNG")
    return buffer.getvalue(), pixel_width, actual_height


def _decode_bgra32_to_rgba(
    xor_data: bytes, width: int, height: int, bottom_up: bool
) -> Image.Image:
    expected_size = width * height * 4
    if len(xor_data) < expected_size:
        raise IcoError("bitmap pixel data is truncated")

    image = Image.new("RGBA", (width, height))
    pixels = image.load()
    if pixels is None:
        raise IcoError("failed to allocate bitmap pixels")

    for y in range(height):
        source_row = (height - 1 - y) if bottom_up else y
        row_offset = source_row * width * 4
        for x in range(width):
            i = row_offset + x * 4
            blue = xor_data[i]
            green = xor_data[i + 1]
            red = xor_data[i + 2]
            alpha = xor_data[i + 3]
            pixels[x, y] = (red, green, blue, alpha)

    return image


def _png_dimensions(payload: bytes) -> tuple[int, int]:
    with Image.open(BytesIO(payload)) as image:
        return image.size
