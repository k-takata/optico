# optico

`optico` is a small command-line tool for ICO files.

It extracts PNG images and 32bpp bitmap images from an `.ico` file, saves them as PNG, preserves non-32bpp bitmap frames as raw `.dib` files, runs `optipng` over the extracted PNG files, and rebuilds a new `.ico` file from the saved frames.

## Usage

Install the package first:

```bash
python -m pip install -e .
```

```bash
python -m optico input.ico --output-dir extracted --rebuild rebuilt.ico
```

Or after installation:

```bash
optico input.ico --output-dir extracted --rebuild rebuilt.ico
```

## Requirements

- Python 3.10+
- Pillow
- `optipng` available on `PATH`
