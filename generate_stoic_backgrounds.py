from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont


QUOTE_FONT_CANDIDATES = [
    Path("C:/Windows/Fonts/segoeuil.ttf"),
    Path("C:/Windows/Fonts/segoeui.ttf"),
    Path("C:/Windows/Fonts/arial.ttf"),
]

AUTHOR_FONT_CANDIDATES = [
    Path("C:/Windows/Fonts/segoeui.ttf"),
    Path("C:/Windows/Fonts/segoeuib.ttf"),
    Path("C:/Windows/Fonts/arial.ttf"),
]


@dataclass
class TextLayout:
    lines: list[str]
    quote_font: ImageFont.FreeTypeFont | ImageFont.ImageFont
    author_font: ImageFont.FreeTypeFont | ImageFont.ImageFont
    author_text: str
    x_center: int
    y_start: int
    line_gap: int
    author_gap: int


def load_json_with_fallbacks(path: Path) -> Any:
    last_error: Exception | None = None
    for encoding in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            with path.open("r", encoding=encoding) as fh:
                return json.load(fh)
        except Exception as exc:  # noqa: BLE001 - keep fallback flow simple
            last_error = exc
    raise RuntimeError(f"Could not parse JSON file: {path}") from last_error


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def slugify(text: str, max_len: int = 32) -> str:
    text = normalize_text(text).lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    if not text:
        return "quote"
    return text[:max_len].strip("-")


def find_icon_bounds(base_image: Image.Image, threshold: int = 10) -> tuple[int, int, int, int] | None:
    grayscale = base_image.convert("L")
    mask = grayscale.point(lambda value: 255 if value > threshold else 0)
    return mask.getbbox()


def get_font(candidates: list[Path], size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for font_path in candidates:
        if font_path.exists():
            try:
                return ImageFont.truetype(str(font_path), size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    left, _, right, _ = draw.textbbox((0, 0), text, font=font)
    return max(0, right - left)


def text_height(draw: ImageDraw.ImageDraw, font: ImageFont.ImageFont) -> int:
    _, top, _, bottom = draw.textbbox((0, 0), "Ag", font=font)
    return max(1, bottom - top)


def split_long_word(
    draw: ImageDraw.ImageDraw,
    word: str,
    font: ImageFont.ImageFont,
    max_width: int,
) -> list[str]:
    chunks: list[str] = []
    current = ""
    for ch in word:
        candidate = f"{current}{ch}"
        if current and text_width(draw, candidate, font) > max_width:
            chunks.append(current)
            current = ch
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
) -> list[str]:
    words = normalize_text(text).split(" ")
    lines: list[str] = []
    current = ""

    for word in words:
        segments = [word]
        if text_width(draw, word, font) > max_width:
            segments = split_long_word(draw, word, font, max_width)

        for segment in segments:
            proposal = segment if not current else f"{current} {segment}"
            if current and text_width(draw, proposal, font) > max_width:
                lines.append(current)
                current = segment
            else:
                current = proposal

    if current:
        lines.append(current)

    return lines or [""]


def build_layout(
    draw: ImageDraw.ImageDraw,
    quote: str,
    author: str,
    image_size: tuple[int, int],
    icon_bbox: tuple[int, int, int, int] | None,
) -> TextLayout:
    image_width, image_height = image_size
    icon_bottom = icon_bbox[3] if icon_bbox else int(image_height * 0.55)
    x_center = ((icon_bbox[0] + icon_bbox[2]) // 2) if icon_bbox else image_width // 2
    author_text = f"- {normalize_text(author).upper()}" if author else ""

    top_gaps = (64, 52, 40, 30, 24)
    bottom_margins = (120, 96, 72, 56, 40)
    width_ratios = (0.56, 0.62, 0.68, 0.74, 0.80, 0.86)

    for top_gap in top_gaps:
        top = icon_bottom + top_gap
        for bottom_margin in bottom_margins:
            available_height = image_height - bottom_margin - top
            if available_height < 120:
                continue

            for width_ratio in width_ratios:
                max_width = int(image_width * width_ratio)

                for font_size in range(78, 11, -1):
                    quote_font = get_font(QUOTE_FONT_CANDIDATES, font_size)
                    author_font = get_font(AUTHOR_FONT_CANDIDATES, max(12, int(font_size * 0.42)))

                    lines = wrap_text(draw, quote, quote_font, max_width)
                    quote_line_height = text_height(draw, quote_font)
                    author_line_height = text_height(draw, author_font) if author_text else 0
                    line_gap = max(4, int(font_size * 0.30))
                    author_gap = max(14, int(font_size * 0.95)) if author_text else 0

                    quote_block_height = (
                        (len(lines) * quote_line_height)
                        + (max(0, len(lines) - 1) * line_gap)
                        + author_gap
                        + author_line_height
                    )

                    if quote_block_height <= available_height:
                        top_padding = min(48, max(20, (available_height - quote_block_height) // 4))
                        y_start = top + top_padding
                        return TextLayout(
                            lines=lines,
                            quote_font=quote_font,
                            author_font=author_font,
                            author_text=author_text,
                            x_center=x_center,
                            y_start=y_start,
                            line_gap=line_gap,
                            author_gap=author_gap,
                        )

    raise RuntimeError("Could not fit text layout without truncation.")


def draw_quote(
    base_image: Image.Image,
    quote: str,
    author: str,
    icon_bbox: tuple[int, int, int, int] | None,
) -> Image.Image:
    composed = base_image.convert("RGBA")
    layout_probe = ImageDraw.Draw(composed)
    layout = build_layout(layout_probe, quote, author, composed.size, icon_bbox)

    glow_layer = Image.new("RGBA", composed.size, (0, 0, 0, 0))
    text_layer = Image.new("RGBA", composed.size, (0, 0, 0, 0))

    glow_draw = ImageDraw.Draw(glow_layer)
    text_draw = ImageDraw.Draw(text_layer)

    quote_color = (240, 240, 240, 245)
    glow_color = (255, 255, 255, 70)
    author_color = (168, 168, 168, 220)

    current_y = layout.y_start
    for line in layout.lines:
        line_w = text_width(layout_probe, line, layout.quote_font)
        line_x = layout.x_center - (line_w // 2)
        glow_draw.text((line_x, current_y), line, font=layout.quote_font, fill=glow_color)
        text_draw.text((line_x, current_y), line, font=layout.quote_font, fill=quote_color)
        current_y += text_height(layout_probe, layout.quote_font) + layout.line_gap

    if layout.author_text:
        current_y += layout.author_gap
        author_w = text_width(layout_probe, layout.author_text, layout.author_font)
        author_x = layout.x_center - (author_w // 2)
        text_draw.text((author_x, current_y), layout.author_text, font=layout.author_font, fill=author_color)

    glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=1.2))
    composed = Image.alpha_composite(composed, glow_layer)
    composed = Image.alpha_composite(composed, text_layer)
    return composed.convert("RGB")


def extract_quotes(data: Any) -> list[dict[str, str]]:
    if isinstance(data, dict):
        if "quotes" in data and isinstance(data["quotes"], list):
            source = data["quotes"]
        else:
            source = []
    elif isinstance(data, list):
        source = data
    else:
        source = []

    cleaned: list[dict[str, str]] = []
    for item in source:
        if not isinstance(item, dict):
            continue
        text = normalize_text(str(item.get("text", "")))
        author = normalize_text(str(item.get("author", "")))
        if text:
            cleaned.append({"text": text, "author": author})
    return cleaned


def output_filename(index: int, quote: str, author: str) -> str:
    author_slug = slugify(author or "stoic", max_len=18)
    quote_slug = slugify(quote, max_len=36)
    return f"stoic_{index:04d}_{author_slug}_{quote_slug}.png"


def generate_wallpapers(
    background_path: Path,
    quotes_path: Path,
    output_dir: Path,
    limit: int | None = None,
) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)

    base_image = Image.open(background_path).convert("RGB")
    icon_bbox = find_icon_bounds(base_image)
    quote_data = extract_quotes(load_json_with_fallbacks(quotes_path))
    if limit is not None:
        quote_data = quote_data[: max(0, limit)]

    if not quote_data:
        raise RuntimeError("No quotes found to render.")

    generated = 0
    for idx, quote_item in enumerate(quote_data, start=1):
        rendered = draw_quote(
            base_image=base_image,
            quote=quote_item["text"],
            author=quote_item["author"],
            icon_bbox=icon_bbox,
        )
        rendered.save(output_dir / output_filename(idx, quote_item["text"], quote_item["author"]))
        generated += 1

    return generated


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate minimalist stoic quote wallpapers from a base background image.",
    )
    parser.add_argument("--background", type=Path, default=Path("background.png"))
    parser.add_argument("--quotes", type=Path, default=Path("stoicquotes.json"))
    parser.add_argument("--output", type=Path, default=Path("stoicbackgrounds"))
    parser.add_argument("--limit", type=int, default=None, help="Optional limit for quick previews")
    args = parser.parse_args()

    created = generate_wallpapers(
        background_path=args.background,
        quotes_path=args.quotes,
        output_dir=args.output,
        limit=args.limit,
    )
    print(f"Generated {created} wallpapers in '{args.output}'.")


if __name__ == "__main__":
    main()