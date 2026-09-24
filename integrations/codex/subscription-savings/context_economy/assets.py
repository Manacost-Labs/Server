"""Explicit local asset preparation into a new directory; originals are immutable."""

import json
import math
import subprocess
import tempfile
import xml.etree.ElementTree as Serializer
from pathlib import Path

from .common import digest, read_source
from .quality_common import SKIP, resource_lock

PRESETS = {
    "hero-art": {"ratio": 16 / 9, "saturation": 0.85, "overlay": 0.35, "text_safe_zone": [0, 0, 0.4, 1]},
    "character-cutout": {"ratio": None, "saturation": 1.0, "padding": 0.08, "transparent": True},
    "card-background": {"ratio": 3 / 2, "saturation": 0.7, "blur": 2, "overlay": 0.25},
    "portrait": {"ratio": 1.0, "saturation": 1.0},
    "decorative-overlay": {"ratio": None, "saturation": 0.8, "opacity": 0.2, "pointer_events": "none"},
}


def normalize_svg(store, args):
    """Validate before SVGO; publish a new file only after validating its output."""
    from defusedxml import ElementTree

    from .design import check_svg

    source = read_source(store.root, args.source)
    destination = safe_path(store.root, args.output)
    if not args.source.endswith(".svg") or destination.suffix != ".svg" or destination.exists():
        raise ValueError("Select an SVG and a new .svg output path")
    tree = ElementTree.fromstring(source["text"], forbid_dtd=True)
    Serializer.register_namespace("", "http://www.w3.org/2000/svg")
    config = {"design": {"allow_multicolor_svg": True,
                         "icon_sizes": [tree.get("width", ""), tree.get("height", "")]}}
    if check_svg(store.root, config, [args.source])["status"] != "passed":
        raise ValueError("Unsafe or invalid SVG; fix validation findings before normalization")
    if args.monochrome:
        for node in tree.iter():
            for name in ("fill", "stroke"):
                value = node.get(name)
                if value and value not in {"none", "inherit", "currentColor"} and not value.startswith("url(#"):
                    node.set(name, "currentColor")
        tree.set("fill", "currentColor")
    quality = Path(__file__).resolve().parents[1] / "quality"
    executable = quality / "node_modules/.bin/svgo"
    if not executable.is_file():
        raise ValueError("Install the pinned quality/package-lock.json dependencies for SVGO")
    with resource_lock(store, "heavy"), tempfile.TemporaryDirectory(prefix="quality-svg-") as scratch:
        temporary = Path(scratch)
        (temporary / "input.svg").write_bytes(Serializer.tostring(tree, encoding="utf-8"))
        subprocess.run([str(executable), "--config", str(quality / "svgo.config.mjs"),
                        "--input", str(temporary / "input.svg"), "--output", str(temporary / "output.svg")],
                       check=True, timeout=30, capture_output=True)
        config["design"]["allow_multicolor_svg"] = not args.monochrome
        if check_svg(temporary, config, ["output.svg"])["status"] != "passed":
            raise ValueError("Normalized SVG failed validation")
        output = (temporary / "output.svg").read_bytes()
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as stream:
            stream.write(output)
    return {"status": "passed", "output": args.output, "bytes": len(output), "source_sha256": source["sha256"]}


def safe_path(root, name):
    path = Path(name)
    if path.is_absolute() or not path.parts or ".." in path.parts or any(p in SKIP or p.startswith(".env") for p in path.parts):
        raise ValueError("Asset paths must be explicit non-protected project-relative paths")
    current = root
    for part in path.parts:
        current /= part
        if current.is_symlink():
            raise ValueError("Symlink asset paths are forbidden")
    return current


def focal_point(image):
    from PIL import ImageFilter, ImageStat
    edges = image.convert("L").resize((96, 96)).filter(ImageFilter.FIND_EDGES)
    # Ignore the filter's artificial outer border. This is a deterministic saliency
    # heuristic, not face/subject recognition; explicit focal coordinates take priority.
    cells = []
    for y in range(3):
        for x in range(3):
            value = ImageStat.Stat(edges.crop((x * 30 + 3, y * 30 + 3, x * 30 + 33, y * 30 + 33))).mean[0]
            cells.append((value, (x + 0.5) / 3, (y + 0.5) / 3))
    chosen = max(cells, key=lambda item: (item[0], -abs(item[1] - 0.5) - abs(item[2] - 0.5)))
    return chosen[1], chosen[2]


def prepare(store, args):
    try:
        from PIL import Image, ImageEnhance, ImageFilter, ImageOps, features
    except ImportError as exc:
        raise ValueError("Asset processing requires requirements-quality.txt (Pillow)") from exc
    if args.preset not in PRESETS:
        raise ValueError("Unknown asset preset")
    if not args.decorative and not args.alt.strip():
        raise ValueError("Provide meaningful --alt or explicitly use --decorative")
    if (args.focal_x is None) != (args.focal_y is None):
        raise ValueError("Supply both focal coordinates")
    if args.focal_x is not None and not all(math.isfinite(v) and 0 <= v <= 1 for v in (args.focal_x, args.focal_y)):
        raise ValueError("Focal coordinates must be finite fractions in [0,1]")
    source, destination = safe_path(store.root, args.source), safe_path(store.root, args.output)
    if not source.is_file() or source.stat().st_size > 25_000_000:
        raise ValueError("Select a regular image no larger than 25 MB")
    if destination.exists():
        raise ValueError("Asset output must be a new directory; existing bundles are never overwritten")
    if not features.check("avif") or not features.check("webp"):
        raise ValueError("Pillow must support AVIF and WebP; install the pinned quality requirements")
    raw = source.read_bytes()
    preset = PRESETS[args.preset]
    with resource_lock(store, "heavy"), tempfile.TemporaryDirectory(prefix="quality-asset-") as scratch:
        with Image.open(source) as original:
            if original.width * original.height > 20_000_000 or getattr(original, "n_frames", 1) != 1:
                raise ValueError("Select a still image no larger than 20 megapixels")
            image = ImageOps.exif_transpose(original).convert("RGBA")
        if args.remove_background:
            release = Path(__file__).resolve().parents[1]
            executable = Path(getattr(args, "background_python", None) or release / ".assets-venv/bin/python")
            model = Path(getattr(args, "background_model", None) or release / "quality/models/u2netp.onnx")
            if not executable.is_file() or not model.is_file():
                raise ValueError("Background removal requires the provisioned CPU environment and pinned local u2netp model")
            cutout = Path(scratch) / "cutout.png"
            subprocess.run([str(executable), str(release / "quality/background_remove.py"),
                            str(source), str(cutout), str(model)], check=True, timeout=120,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            with Image.open(cutout) as processed:
                image = processed.convert("RGBA")
        if preset.get("transparent") and image.getchannel("A").getextrema()[0] == 255:
            raise ValueError("Cutout preset requires an existing alpha channel or explicit background removal")
        focal = (args.focal_x, args.focal_y) if args.focal_x is not None else focal_point(image)
        original_size = image.size
        palette_image = image.convert("RGB").resize((64, 64)).quantize(colors=5)
        palette = palette_image.getpalette()
        colors = ["#%02x%02x%02x" % tuple(palette[index * 3:index * 3 + 3])
                  for _, index in sorted(palette_image.getcolors(), reverse=True)]
        image = ImageEnhance.Color(image).enhance(preset["saturation"])
        if preset.get("blur"):
            image = image.filter(ImageFilter.GaussianBlur(preset["blur"]))
        if preset.get("padding"):
            border = int(max(image.size) * preset["padding"])
            image = ImageOps.expand(image, border, fill=(0, 0, 0, 0))
        if preset.get("opacity"):
            image.putalpha(image.getchannel("A").point(lambda value: round(value * preset["opacity"])))
        variants = []
        widths = [width for width in (320, 640, 960, 1440) if width <= image.width] or [image.width]
        for width in widths:
            height = round(width / preset["ratio"]) if preset["ratio"] else round(width * image.height / image.width)
            variant = ImageOps.fit(image, (width, max(1, height)), method=Image.Resampling.LANCZOS, centering=focal)
            for suffix, format_name in (("avif", "AVIF"), ("webp", "WEBP")):
                filename = f"{args.preset}-{width}.{suffix}"
                target = Path(scratch) / filename
                variant.save(target, format=format_name, quality=80)
                variants.append({"file": filename, "width": width, "height": max(1, height),
                                 "format": suffix, "bytes": target.stat().st_size})
        metadata = {"version": 1, "source": args.source, "source_sha256": digest(raw), "preset": args.preset,
                    "alt": "" if args.decorative else args.alt, "decorative": args.decorative,
                    "original_size": original_size, "focal_point": focal,
                    "focal_method": "explicit" if args.focal_x is not None else "edge-saliency heuristic",
                    "dominant_colors": colors, "presentation": preset, "variants": variants}
        if args.remove_background:
            metadata["background_removal"] = {"model": "u2netp", "model_sha256": digest(model.read_bytes()),
                                               "backend": "rembg CPU", "runtime_download": False}
        (Path(scratch) / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
        # Publish only after every conversion succeeded; refuse a concurrent destination.
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.mkdir()
        for item in variants + [{"file": "metadata.json"}]:
            with (destination / item["file"]).open("xb") as out:
                out.write((Path(scratch) / item["file"]).read_bytes())
    return {"status": "passed", "output": args.output, "metadata": str(destination / "metadata.json"),
            "variants": len(variants), "source_sha256": metadata["source_sha256"]}
