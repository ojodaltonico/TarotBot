"""Download and normalize the public-domain RWS runtime deck from its manifest."""

from __future__ import annotations

import argparse
import json
import sys
import time
from io import BytesIO
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zipfile import ZipFile

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "assets" / "tarot-cards" / "manifest.json"
CARDS_DIR = ROOT / "assets" / "tarot-cards" / "cards"
DECK_PATH = ROOT / "backend" / "app" / "tarot" / "data" / "deck.json"
USER_AGENT = "TarotBot asset normalizer/1.0 (local development)"
TAROT_JSON_ARCHIVE = "https://codeload.github.com/metabismuth/tarot-json/zip/refs/heads/master"


class DownloadError(RuntimeError):
    pass


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_manifest(manifest: dict) -> list[str]:
    expected_ids = {card["id"] for card in _load_json(DECK_PATH)["cards"]}
    entries = manifest.get("cards", [])
    actual_ids = [entry.get("card_id") for entry in entries]
    problems: list[str] = []
    if len(entries) != 78:
        problems.append(f"manifest contiene {len(entries)} cartas; se esperaban 78")
    if len(actual_ids) != len(set(actual_ids)):
        problems.append("manifest contiene card_id duplicados")
    if set(actual_ids) != expected_ids:
        problems.append("los card_id del manifest no coinciden exactamente con deck.json")
    for entry in entries:
        required = {"card_id", "filename", "source_url", "source_collection", "author", "original_year", "license_status", "source_file_identifier"}
        missing = required.difference(entry)
        if missing:
            problems.append(f"{entry.get('card_id', '<sin id>')}: faltan {', '.join(sorted(missing))}")
        elif entry["filename"] != f"{entry['card_id']}.webp":
            problems.append(f"{entry['card_id']}: filename no está normalizado por card_id")
    return problems


def validate_runtime(manifest: dict) -> list[str]:
    problems = validate_manifest(manifest)
    for entry in manifest["cards"]:
        path = CARDS_DIR / entry["filename"]
        if not path.exists():
            problems.append(f"falta {path.name}")
            continue
        try:
            with Image.open(path) as image:
                width, height = image.size
                if image.format != "WEBP":
                    problems.append(f"{path.name}: formato {image.format}, se esperaba WEBP")
                if not 700 <= height <= 900:
                    problems.append(f"{path.name}: alto {height}, se esperaba 700-900")
                if width >= height:
                    problems.append(f"{path.name}: la proporción no es vertical")
        except OSError:
            problems.append(f"{path.name}: archivo de imagen ilegible")
    return problems


def _thumbnail_urls(entries: list[dict]) -> dict[str, str]:
    """Resolve the whole verified Commons collection once, then download its CDN thumbnails."""
    available: dict[str, str] = {}
    continuation: dict[str, str] | None = None
    while True:
        params = {
            "action": "query", "format": "json", "generator": "categorymembers",
            "gcmtitle": "Category:Rider-Waite-Smith tarot deck (Geldard)", "gcmtype": "file", "gcmlimit": "500",
            "prop": "imageinfo", "iiprop": "url", "iiurlheight": "840",
        }
        if continuation:
            params.update(continuation)
        request = Request(f"https://commons.wikimedia.org/w/api.php?{urlencode(params)}", headers={"User-Agent": USER_AGENT})
        with urlopen(request, timeout=30) as response:
            if response.status != 200:
                raise DownloadError(f"Wikimedia respondió HTTP {response.status} al consultar la colección")
            payload = json.load(response)
        for page in payload.get("query", {}).get("pages", {}).values():
            identifier = str(page.get("title", "")).removeprefix("File:")
            info = (page.get("imageinfo") or [{}])[0]
            url = info.get("thumburl") or info.get("url")
            if identifier and url:
                available[identifier] = str(url)
        continuation = payload.get("continue")
        if not continuation:
            break
    missing = [entry["source_file_identifier"] for entry in entries if entry["source_file_identifier"] not in available]
    if missing:
        raise DownloadError(f"La colección no devolvió {len(missing)} archivo(s) esperado(s): {', '.join(missing[:3])}")
    return {entry["card_id"]: available[entry["source_file_identifier"]] for entry in entries}


def _download_and_normalize(entry: dict, url: str, *, overwrite: bool) -> str:
    CARDS_DIR.mkdir(parents=True, exist_ok=True)
    destination = CARDS_DIR / entry["filename"]
    if destination.exists() and not overwrite:
        return "existing"
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=60) as response:
        if response.status != 200:
            raise DownloadError(f"Wikimedia respondió HTTP {response.status} al descargar {entry['card_id']}")
        raw = response.read()
    with Image.open(BytesIO(raw)) as source:
        image = source.convert("RGB")
        image.thumbnail((600, 840), Image.Resampling.LANCZOS)
        if image.height < 700:
            ratio = 700 / image.height
            image = image.resize((round(image.width * ratio), 700), Image.Resampling.LANCZOS)
        image.save(destination, "WEBP", quality=88, method=6)
    return "downloaded"


def _tarot_json_filename(card_id: str) -> str:
    if card_id.startswith("major_"):
        return f"m{int(card_id.split('_')[1]):02d}.jpg"
    suit, number, _ = card_id.split("_", 2)
    prefix = {"wands": "w", "cups": "c", "swords": "s", "pentacles": "p"}[suit]
    return f"{prefix}{int(number):02d}.jpg"


def _download_from_tarot_json(entries: list[dict], *, overwrite: bool) -> None:
    """Explicit low-request mirror for the same public-domain RWS scans when Commons throttles automation."""
    request = Request(TAROT_JSON_ARCHIVE, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=90) as response:
        if response.status != 200:
            raise DownloadError(f"el espejo tarot-json respondió HTTP {response.status}")
        archive = response.read()
    CARDS_DIR.mkdir(parents=True, exist_ok=True)
    with ZipFile(BytesIO(archive)) as bundle:
        names = set(bundle.namelist())
        for index, entry in enumerate(entries, start=1):
            destination = CARDS_DIR / entry["filename"]
            if destination.exists() and not overwrite:
                print(f"[{index}/78] {entry['card_id']}: existing")
                continue
            source_name = f"tarot-json-master/cards/{_tarot_json_filename(entry['card_id'])}"
            if source_name not in names:
                raise DownloadError(f"el espejo no contiene {source_name}")
            with Image.open(BytesIO(bundle.read(source_name))) as source:
                image = source.convert("RGB")
                image.thumbnail((600, 840), Image.Resampling.LANCZOS)
                if image.height < 700:
                    ratio = 700 / image.height
                    image = image.resize((round(image.width * ratio), 700), Image.Resampling.LANCZOS)
                image.save(destination, "WEBP", quality=88, method=6)
            print(f"[{index}/78] {entry['card_id']}: mirrored")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validate", action="store_true", help="only validate manifest and local runtime files")
    parser.add_argument("--force", action="store_true", help="replace existing normalized runtime files")
    parser.add_argument("--source", choices=("commons", "tarot-json"), default="commons", help="download source; tarot-json is an explicit low-request RWS mirror")
    args = parser.parse_args()
    manifest = _load_json(MANIFEST_PATH)
    manifest_problems = validate_manifest(manifest)
    if manifest_problems:
        print("Manifest inválido:", *manifest_problems, sep="\n- ")
        return 1
    if args.validate:
        problems = validate_runtime(manifest)
        if problems:
            print("Validación incompleta:", *problems, sep="\n- ")
            return 1
        total = sum((CARDS_DIR / item["filename"]).stat().st_size for item in manifest["cards"])
        print(f"78/78 imágenes runtime válidas ({total / 1024 / 1024:.2f} MiB).")
        return 0
    if args.source == "tarot-json":
        try:
            _download_from_tarot_json(manifest["cards"], overwrite=args.force)
        except (DownloadError, OSError) as error:
            print(f"No se pudo descargar el espejo: {error}", file=sys.stderr)
            return 1
        return main_validate(manifest)
    pending = [entry for entry in manifest["cards"] if args.force or not (CARDS_DIR / entry["filename"]).exists()]
    try:
        urls = _thumbnail_urls(pending) if pending else {}
    except (DownloadError, OSError) as error:
        print(f"No se pudo resolver la colección: {error}", file=sys.stderr)
        return 1
    for index, entry in enumerate(manifest["cards"], start=1):
        try:
            status = _download_and_normalize(entry, urls.get(entry["card_id"], ""), overwrite=args.force)
        except (DownloadError, OSError) as error:
            print(f"[{index}/78] {entry['card_id']}: ERROR: {error}", file=sys.stderr)
            return 1
        print(f"[{index}/78] {entry['card_id']}: {status}")
        if status == "downloaded":
            time.sleep(7.0)  # Commons CDN rate courtesy; this is not a retry.
    return main_validate(manifest)


def main_validate(manifest: dict) -> int:
    problems = validate_runtime(manifest)
    if problems:
        print("Validación incompleta:", *problems, sep="\n- ")
        return 1
    total = sum((CARDS_DIR / item["filename"]).stat().st_size for item in manifest["cards"])
    print(f"78/78 imágenes runtime válidas ({total / 1024 / 1024:.2f} MiB).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
