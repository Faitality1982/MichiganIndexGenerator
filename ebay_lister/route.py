"""
eBay or Facebook Marketplace: the decision and the Facebook draft.

Claude fills the "routing" block of listing.json (weight, size, price estimates);
decide() applies fixed rules to it so the same item always routes the same way.
Facebook has no listing API for individual sellers, so a Facebook item ends as a
facebook/ folder (listing.txt + numbered photos) the user posts in the Seller app.
"""

import html
import re
import shutil
from pathlib import Path

EBAY = "ebay"
FACEBOOK = "facebook"
ASK = "ask"

FB_DIR = "facebook"
FB_TEXT = "listing.txt"

# Rule thresholds. Override any of them in config.json under "routing".
# The fee rate is an approximation of eBay's final value fee for most
# categories - check it against eBay's current fee page and adjust.
DEFAULTS = {
    "ebay_fee_rate": 0.136,       # final value fee, share of item price + shipping
    "ebay_fee_per_order": 0.40,   # per-order fee
    "max_ship_weight_lb": 70,     # heavier than this goes local
    "max_ship_length_girth_in": 130,   # longest side + 2*(the other two)
    "min_ebay_net": 25.0,         # below this, eBay isn't worth packing and shipping
    "ebay_margin_abs": 15.0,      # eBay must beat local by this much...
    "ebay_margin_pct": 0.25,      # ...or this share of the local price, whichever is more
    "fb_max_photos": 10,
}

FB_CONDITIONS = ("New", "Used - Like New", "Used - Good", "Used - Fair")

ROUTING_TEMPLATE = {
    "weight_lb": None,            # packed weight estimate
    "dims_in": [],                # [l, w, h] packed, inches
    "local_only": "",             # reason it can't ship at all, e.g. "refrigerator"
    "ebay_price_est": None,       # what it should sell for on eBay
    "ship_cost_est": None,        # what the shipping label costs
    "free_shipping": False,       # True if the seller pays shipping
    "local_price_est": None,      # what it should sell for locally on Facebook
    "decision": "",               # written by `route`
}

FACEBOOK_TEMPLATE = {
    "title": "",                  # blank = eBay title
    "price": None,                # blank = routing.local_price_est
    "condition": "",              # one of FB_CONDITIONS
    "category": "",               # Marketplace category, e.g. "Appliances"
    "description": "",            # plain text; blank = eBay description as text
}


def settings(cfg):
    return {**DEFAULTS, **((cfg or {}).get("routing") or {})}


def _num(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def length_girth(dims):
    sides = sorted((float(d) for d in dims), reverse=True)
    return sides[0] + 2 * (sides[1] + sides[2])


def ebay_net(price, ship_cost, free_shipping, s):
    """What the seller keeps after eBay fees (and shipping, if they pay it)."""
    ship_cost = ship_cost or 0.0
    charged = price + (0.0 if free_shipping else ship_cost)
    net = price - s["ebay_fee_rate"] * charged - s["ebay_fee_per_order"]
    return net - ship_cost if free_shipping else net


def decide(routing, cfg=None):
    """Returns (channel, reasons, numbers). channel is EBAY, FACEBOOK or ASK."""
    s = settings(cfg)
    r = {**ROUTING_TEMPLATE, **(routing or {})}
    reasons, numbers = [], {}

    if (r.get("local_only") or "").strip():
        return FACEBOOK, [f"local only: {r['local_only'].strip()}"], numbers

    weight = _num(r.get("weight_lb"))
    if weight is not None and weight > s["max_ship_weight_lb"]:
        return FACEBOOK, [f"{weight:g} lb is over the {s['max_ship_weight_lb']:g} lb shipping limit"], numbers

    dims = r.get("dims_in") or []
    if len(dims) == 3 and all(_num(d) is not None for d in dims):
        lg = length_girth(dims)
        numbers["length_girth_in"] = round(lg, 1)
        if lg > s["max_ship_length_girth_in"]:
            return FACEBOOK, [f"length + girth {lg:g} in is over {s['max_ship_length_girth_in']:g} in"], numbers

    missing = [k for k in ("ebay_price_est", "local_price_est") if _num(r.get(k)) is None]
    if _num(r.get("ship_cost_est")) is None:
        missing.append("ship_cost_est")
    if weight is None:
        missing.append("weight_lb")
    if missing:
        return ASK, [f"routing is missing: {', '.join(missing)}"], numbers

    net = ebay_net(r["ebay_price_est"], r["ship_cost_est"], r.get("free_shipping"), s)
    local = float(r["local_price_est"])
    margin = max(s["ebay_margin_abs"], s["ebay_margin_pct"] * local)
    numbers.update({"ebay_net": round(net, 2), "local_net": round(local, 2),
                    "margin_needed": round(margin, 2)})

    if net < s["min_ebay_net"]:
        return FACEBOOK, [f"eBay would net ${net:.2f}, under ${s['min_ebay_net']:.2f}"], numbers
    if net >= local + margin:
        reasons.append(f"eBay nets ${net:.2f} vs ${local:.2f} local (needs +${margin:.2f})")
        return EBAY, reasons, numbers
    if net > local:
        reasons.append(f"eBay nets ${net:.2f} vs ${local:.2f} local - ahead, but by less "
                       f"than ${margin:.2f}")
        return ASK, reasons, numbers
    return FACEBOOK, [f"local ${local:.2f} matches or beats eBay's ${net:.2f}"], numbers


# ══════════════════════════════════════════════════════════════════════════════
#  FACEBOOK DRAFT
# ══════════════════════════════════════════════════════════════════════════════

def html_to_text(markup):
    """eBay description HTML -> plain text for Facebook."""
    text = re.sub(r"(?i)<\s*li[^>]*>", "- ", markup or "")
    text = re.sub(r"(?i)<\s*(br|/p|/li|/ul|/ol|/h\d|/div)[^>]*>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def facebook_fields(listing):
    """The Facebook listing: listing["facebook"] where set, else derived from
    the eBay draft and the local price estimate."""
    fb = listing.get("facebook") or {}
    routing = listing.get("routing") or {}
    return {
        "title": (fb.get("title") or listing.get("title") or "").strip(),
        "price": _num(fb.get("price")) or _num(routing.get("local_price_est")),
        "condition": (fb.get("condition") or "").strip(),
        "category": (fb.get("category") or "").strip(),
        "description": (fb.get("description") or
                        html_to_text(listing.get("description_html") or "")).strip(),
    }


def facebook_problems(fields):
    problems = []
    if not fields["title"]:
        problems.append("title is empty")
    if not fields["price"] or fields["price"] <= 0:
        problems.append('no price (set facebook.price or routing.local_price_est)')
    if fields["condition"] not in FB_CONDITIONS:
        problems.append(f"facebook.condition must be one of: {', '.join(FB_CONDITIONS)}")
    if not fields["description"]:
        problems.append("description is empty")
    return problems


def write_facebook_draft(folder, fields, photos, cfg=None):
    """Writes facebook/listing.txt and copies photos as 01.jpg, 02.jpg, ...
    Returns the facebook/ folder."""
    s = settings(cfg)
    out = Path(folder) / FB_DIR
    out.mkdir(exist_ok=True)
    for old in out.glob("*.jpg"):
        old.unlink()
    used = list(photos)[: s["fb_max_photos"]]
    for i, src in enumerate(used, 1):
        shutil.copyfile(src, out / f"{i:02d}.jpg")

    location = (cfg or {}).get("location") or ""
    lines = [
        f"TITLE: {fields['title']}",
        f"PRICE: {fields['price']:.0f}" if float(fields["price"]).is_integer()
        else f"PRICE: {fields['price']:.2f}",
        f"CONDITION: {fields['condition']}",
    ]
    if fields["category"]:
        lines.append(f"CATEGORY: {fields['category']}")
    if location:
        lines.append(f"LOCATION: {location}")
    lines += ["", "DESCRIPTION:", fields["description"], "",
              f"PHOTOS: {len(used)} in this folder, in order (01.jpg is the cover)"]
    (out / FB_TEXT).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out
