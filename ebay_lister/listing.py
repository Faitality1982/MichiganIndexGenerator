"""
Item folders, photos, listing.json validation, and the Trading API XML.

An item folder looks like:

    brass-lamp/
        IMG_4471.HEIC  IMG_4472.jpg ...   original photos (never modified)
        prepared/                          web-ready JPEGs made by `prep`
        listing.json                       the listing (written by Claude / you)
        ebay_state.json                    managed by the tool: photo URLs, ItemID
"""

import hashlib
import json
import re
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image, ImageOps

try:  # iPhone HEIC support is optional:  pip install pillow-heif
    import pillow_heif
    pillow_heif.register_heif_opener()
    HEIC_OK = True
except ImportError:
    HEIC_OK = False


LISTING_FILE = "listing.json"
STATE_FILE = "ebay_state.json"
PREPARED_DIR = "prepared"

PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff",
              ".heic", ".heif"}
MAX_PHOTOS = 24          # eBay's free-photo limit for almost every category
MIN_LONG_SIDE = 500      # eBay rejects photos smaller than this
TARGET_LONG_SIDE = 1600  # eBay's recommended size (enables zoom)
TITLE_MAX = 80
CONDITION_DESC_MAX = 1000
SPECIFIC_MAX = 65        # max length of an item-specific name or value

FIXED = "FixedPriceItem"
AUCTION = "Chinese"
AUCTION_DURATIONS = {"Days_1", "Days_3", "Days_5", "Days_7", "Days_10"}

LISTING_TEMPLATE = {
    "title": "",
    "category_id": "",
    "category_name": "",
    "condition_id": 3000,
    "condition_description": "",
    "item_specifics": {},
    "description_html": "",
    "price": None,
    "best_offer": True,
    "listing_type": FIXED,
    "duration": "GTC",
    "quantity": 1,
    "sku": "",
    "photos": [],
    "seller_notes": [],
}


def natural_key(name):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


# ══════════════════════════════════════════════════════════════════════════════
#  FILES
# ══════════════════════════════════════════════════════════════════════════════

def _read_json(path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_listing(folder):
    path = Path(folder) / LISTING_FILE
    if not path.exists():
        raise FileNotFoundError(f"No {LISTING_FILE} in {folder}. Run `prep` first.")
    return {**LISTING_TEMPLATE, **_read_json(path, {})}


def save_listing(folder, listing):
    _write_json(Path(folder) / LISTING_FILE, listing)


def load_state(folder):
    return _read_json(Path(folder) / STATE_FILE, {})


def save_state(folder, state):
    _write_json(Path(folder) / STATE_FILE, state)


def sha1_file(path):
    return hashlib.sha1(Path(path).read_bytes()).hexdigest()


# ══════════════════════════════════════════════════════════════════════════════
#  PHOTOS
# ══════════════════════════════════════════════════════════════════════════════

def source_photos(folder):
    folder = Path(folder)
    return sorted((p for p in folder.iterdir()
                   if p.is_file() and p.suffix.lower() in PHOTO_EXTS),
                  key=lambda p: natural_key(p.name))


def prepare_photos(folder):
    """Make web-ready copies in prepared/: upright (EXIF rotation applied),
    JPEG, longest side <= 1600px, all metadata stripped (incl. GPS).
    Returns [(source_name, prepared_name, (w, h))]."""
    folder = Path(folder)
    sources = source_photos(folder)
    heic = [p.name for p in sources if p.suffix.lower() in (".heic", ".heif")]
    if heic and not HEIC_OK:
        raise RuntimeError(f"{len(heic)} HEIC photo(s) found ({heic[0]}...). "
                           f"Install HEIC support:  pip install pillow-heif")
    out_dir = folder / PREPARED_DIR
    out_dir.mkdir(exist_ok=True)
    for old in out_dir.glob("*.jpg"):
        old.unlink()

    results, used = [], set()
    for src in sources:
        name = f"{src.stem}.jpg"
        n = 2
        while name.lower() in used:           # IMG_1.heic + IMG_1.jpg
            name = f"{src.stem}_{n}.jpg"
            n += 1
        used.add(name.lower())

        with Image.open(src) as original:
            icc = original.info.get("icc_profile")   # keep colors right (iPhone P3)
            img = ImageOps.exif_transpose(original)
            if img.mode in ("RGBA", "LA", "P", "PA"):
                img = img.convert("RGBA")
                bg = Image.new("RGB", img.size, "white")
                bg.paste(img, mask=img.getchannel("A"))
                img = bg
            elif img.mode != "RGB":
                img = img.convert("RGB")
            img.thumbnail((TARGET_LONG_SIDE, TARGET_LONG_SIDE), Image.LANCZOS)
            img.info = {}                             # drop EXIF/XMP (GPS, device)
            img.save(out_dir / name, "JPEG", quality=90, optimize=True,
                     **({"icc_profile": icc} if icc else {}))
            results.append((src.name, name, img.size))
    return results


def photo_paths(folder, listing):
    """Prepared photos in listing order (listing.photos, else name order)."""
    prepared = Path(folder) / PREPARED_DIR
    if listing.get("photos"):
        return [prepared / name for name in listing["photos"]]
    if not prepared.exists():
        return []
    return sorted(prepared.glob("*.jpg"), key=lambda p: natural_key(p.name))


# ══════════════════════════════════════════════════════════════════════════════
#  VALIDATION
# ══════════════════════════════════════════════════════════════════════════════

def validate(folder, listing, cfg):
    """Local checks before anything is sent to eBay. Returns (errors, warnings)."""
    errors, warnings = [], []

    title = (listing.get("title") or "").strip()
    if not title:
        errors.append("title is empty")
    elif len(title) > TITLE_MAX:
        errors.append(f"title is {len(title)} characters (max {TITLE_MAX})")

    if not str(listing.get("category_id") or "").strip():
        errors.append("category_id is empty - run `category`")

    price = listing.get("price")
    if isinstance(price, bool) or not isinstance(price, (int, float)) or price <= 0:
        errors.append("price is not set (must be a number, e.g. 24.99)")

    if not (listing.get("description_html") or "").strip():
        errors.append("description_html is empty")

    ltype = listing.get("listing_type")
    duration = listing.get("duration")
    if ltype == FIXED:
        if duration != "GTC":
            errors.append('fixed-price listings must use duration "GTC"')
    elif ltype == AUCTION:
        if duration not in AUCTION_DURATIONS:
            errors.append(f"auction duration must be one of {sorted(AUCTION_DURATIONS)}")
        if listing.get("quantity") != 1:
            errors.append("auctions must have quantity 1")
    else:
        errors.append(f'listing_type must be "{FIXED}" or "{AUCTION}"')

    qty = listing.get("quantity")
    if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
        errors.append("quantity must be a whole number >= 1")

    if len(listing.get("condition_description") or "") > CONDITION_DESC_MAX:
        errors.append(f"condition_description is over {CONDITION_DESC_MAX} characters")

    for name, value in (listing.get("item_specifics") or {}).items():
        values = value if isinstance(value, list) else [value]
        if len(name) > SPECIFIC_MAX:
            errors.append(f'item specific name "{name[:30]}..." is over {SPECIFIC_MAX} chars')
        for v in values:
            if not str(v).strip():
                errors.append(f'item specific "{name}" has an empty value')
            elif len(str(v)) > SPECIFIC_MAX:
                errors.append(f'item specific "{name}" value is over {SPECIFIC_MAX} chars')

    photos = photo_paths(folder, listing)
    if not photos:
        errors.append("no photos - run `prep`")
    elif len(photos) > MAX_PHOTOS:
        errors.append(f"{len(photos)} photos (eBay max {MAX_PHOTOS})")
    for p in photos:
        if not p.exists():
            errors.append(f"photo not found: {PREPARED_DIR}/{p.name}")
            continue
        with Image.open(p) as img:
            if max(img.size) < MIN_LONG_SIDE:
                warnings.append(f"{p.name} is {img.size[0]}x{img.size[1]} - eBay may "
                                f"reject photos under {MIN_LONG_SIDE}px on the long side")

    if not cfg.get("postal_code"):
        errors.append("postal_code is empty in config.json")
    for kind in ("shipping", "payment", "return"):
        if not cfg["policies"].get(kind):
            errors.append(f"no {kind} policy in config.json - run `policies`")

    for note in listing.get("seller_notes") or []:
        warnings.append(f"unresolved note: {note}")

    return errors, warnings


# ══════════════════════════════════════════════════════════════════════════════
#  TRADING API XML
# ══════════════════════════════════════════════════════════════════════════════

def new_uuid():
    """Item.UUID: 32 hex chars, uppercase. Makes AddItem safe to retry."""
    return uuid.uuid4().hex.upper()


def _add(parent, tag, text=None, **attrs):
    el = ET.SubElement(parent, tag, attrs)
    if text is not None:
        el.text = str(text)
    return el


def full_description(listing, cfg):
    html = listing["description_html"].strip()
    footer = (cfg.get("description_footer_html") or "").strip()
    return f"{html}\n{footer}" if footer else html


def build_item_xml(call_name, listing, cfg, picture_urls, item_uuid):
    """AddItem / VerifyAddItem request body (bytes). HTML in the description is
    XML-escaped by ElementTree, which eBay reads the same as CDATA."""
    root = ET.Element(f"{call_name}Request", xmlns="urn:ebay:apis:eBLBaseComponents")
    _add(root, "ErrorLanguage", "en_US")
    _add(root, "WarningLevel", "High")
    item = _add(root, "Item")

    _add(item, "Title", listing["title"].strip())
    _add(item, "Description", full_description(listing, cfg))
    _add(_add(item, "PrimaryCategory"), "CategoryID", str(listing["category_id"]).strip())
    _add(item, "StartPrice", f'{float(listing["price"]):.2f}', currencyID=cfg["currency"])

    condition_id = listing.get("condition_id")
    if condition_id:
        _add(item, "ConditionID", int(condition_id))
        note = (listing.get("condition_description") or "").strip()
        if note and not 1000 <= int(condition_id) < 1500:   # ignored for New
            _add(item, "ConditionDescription", note)

    _add(item, "Country", cfg["country"])
    _add(item, "Currency", cfg["currency"])
    if cfg.get("location"):
        _add(item, "Location", cfg["location"])
    _add(item, "PostalCode", cfg["postal_code"])

    _add(item, "ListingType", listing["listing_type"])
    _add(item, "ListingDuration", listing["duration"])
    _add(item, "Quantity", int(listing["quantity"]))
    if listing.get("best_offer"):
        _add(_add(item, "BestOfferDetails"), "BestOfferEnabled", "true")
    if (listing.get("sku") or "").strip():
        _add(item, "SKU", listing["sku"].strip())
    _add(item, "UUID", item_uuid)

    pictures = _add(item, "PictureDetails")
    for url in picture_urls:
        _add(pictures, "PictureURL", url)

    specifics = listing.get("item_specifics") or {}
    if specifics:
        container = _add(item, "ItemSpecifics")
        for name, value in specifics.items():
            nvl = _add(container, "NameValueList")
            _add(nvl, "Name", name)
            for v in (value if isinstance(value, list) else [value]):
                _add(nvl, "Value", v)

    profiles = _add(item, "SellerProfiles")
    _add(_add(profiles, "SellerShippingProfile"), "ShippingProfileID", cfg["policies"]["shipping"])
    _add(_add(profiles, "SellerReturnProfile"), "ReturnProfileID", cfg["policies"]["return"])
    _add(_add(profiles, "SellerPaymentProfile"), "PaymentProfileID", cfg["policies"]["payment"])

    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


# ══════════════════════════════════════════════════════════════════════════════
#  PHOTO UPLOAD CACHE
# ══════════════════════════════════════════════════════════════════════════════

def cached_photo_url(state, env, path):
    """Reuse an uploaded photo if the file is unchanged and eBay won't expire it
    within a day. Unused eBay-hosted photos expire; listed ones don't."""
    entry = state.get("photos", {}).get(env, {}).get(path.name)
    if not entry or entry.get("sha1") != sha1_file(path):
        return None
    expires = entry.get("expires")
    if expires:
        try:
            when = datetime.fromisoformat(expires.replace("Z", "+00:00"))
            if when - datetime.now(timezone.utc) < timedelta(days=1):
                return None
        except ValueError:
            pass
    return entry["url"]


def remember_photo(state, env, path, url, expires):
    state.setdefault("photos", {}).setdefault(env, {})[path.name] = {
        "sha1": sha1_file(path), "url": url, "expires": expires}
