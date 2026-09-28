"""
eBay Lister - turn a folder of item photos into a live eBay listing.

Claude (in Claude Code) looks at the photos and writes listing.json; this tool
handles everything that talks to eBay. Run `python ebay_lister.py -h` for help.

One-time setup:
    python ebay_lister.py setup          create ~/.ebay_lister/config.json
    python ebay_lister.py auth           sign in to eBay (good ~18 months)
    python ebay_lister.py policies       pick shipping/payment/return policies

Per item:
    python ebay_lister.py prep     FOLDER   resize/rotate photos, strip GPS, make listing.json
    python ebay_lister.py category FOLDER   choose category; see required item specifics
    python ebay_lister.py comps    FOLDER   active listings for price reference
    python ebay_lister.py verify   FOLDER   dry run with eBay: errors + fees, lists nothing
    python ebay_lister.py publish  FOLDER   list it for real (asks first)
    python ebay_lister.py status   FOLDER   what's drafted / listed under a folder
"""

import argparse
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path

import requests

import ebay_api
import listing as lst
from ebay_api import EbayClient, EbayError


def out(text=""):
    print(text, flush=True)


def _folder(path):
    folder = Path(path).expanduser().resolve()
    if not folder.is_dir():
        raise EbayError(f"Not a folder: {folder}")
    return folder


# ══════════════════════════════════════════════════════════════════════════════
#  ONE-TIME SETUP
# ══════════════════════════════════════════════════════════════════════════════

def cmd_setup(args):
    if ebay_api.CONFIG_PATH.exists():
        out(f"Config already exists: {ebay_api.CONFIG_PATH}")
    else:
        ebay_api.save_config(ebay_api.CONFIG_TEMPLATE)
        out(f"Created {ebay_api.CONFIG_PATH}")
    out("\nFill in client_id, client_secret, ru_name (from developer.ebay.com),")
    out("postal_code and location. Then run:  python ebay_lister.py auth")


def cmd_auth(args):
    client = EbayClient(ebay_api.load_config())
    redirect = args.redirect_url
    if not redirect:
        out("1. Open this URL, sign in to the eBay account you sell from, click Agree:\n")
        out(client.consent_url())
        out("\n2. Copy the full URL of the page eBay sends you to (it contains code=...).")
        if not sys.stdin.isatty():
            out('3. Run:  python ebay_lister.py auth --redirect-url "<that URL>"')
            out("   (the code expires about 5 minutes after you click Agree)")
            return 0
        redirect = input("\nPaste it here: ")
    client.exchange_code(redirect)
    days = client.refresh_token_days_left() or 0
    out(f"\nSigned in ({client.env}). Sign-in stays valid for about {days:.0f} days.")
    out("Next:  python ebay_lister.py policies")
    return 0


def cmd_policies(args):
    raw = json.loads(ebay_api.CONFIG_PATH.read_text(encoding="utf-8")) \
        if ebay_api.CONFIG_PATH.exists() else {}
    cfg = ebay_api.load_config()
    chosen = {"shipping": args.shipping, "payment": args.payment, "return": args.return_}
    if any(chosen.values()):
        raw.setdefault("policies", {})
        for kind, value in chosen.items():
            if value:
                raw["policies"][kind] = value
        ebay_api.save_config({**ebay_api.CONFIG_TEMPLATE, **raw})
        out(f"Saved to {ebay_api.CONFIG_PATH}: {raw['policies']}")
        return 0

    policies = EbayClient(cfg).business_policies()
    for kind, rows in policies.items():
        out(f"\n{kind.upper()} policies:")
        if not rows:
            out("  (none - create one in Seller Hub > Account > Business policies)")
        for pid, name in rows:
            mark = "*" if cfg["policies"].get(kind) == pid else " "
            out(f" {mark} {pid}  {name}")
    out("\n* = currently configured. To choose:")
    out("  python ebay_lister.py policies --shipping ID --payment ID --return ID")
    return 0


# ══════════════════════════════════════════════════════════════════════════════
#  PER-ITEM
# ══════════════════════════════════════════════════════════════════════════════

def cmd_prep(args):
    folder = _folder(args.folder)
    results = lst.prepare_photos(folder)
    if not results:
        raise EbayError(f"No photos found in {folder}")
    out(f"Prepared {len(results)} photo(s) in {folder / lst.PREPARED_DIR}:")
    for src, name, (w, h) in results:
        flag = "   <-- under 500px, eBay may reject" if max(w, h) < lst.MIN_LONG_SIDE else ""
        out(f"  {name:<32} {w}x{h}  (from {src}){flag}")
    if len(results) > lst.MAX_PHOTOS:
        out(f"\nNote: eBay allows {lst.MAX_PHOTOS} photos; list the ones to use in "
            f'listing.json "photos".')

    if (folder / lst.LISTING_FILE).exists():
        out(f"\n{lst.LISTING_FILE} already exists - left unchanged.")
    else:
        lst.save_listing(folder, dict(lst.LISTING_TEMPLATE))
        out(f"\nCreated {lst.LISTING_FILE} template.")
    return 0


def _print_aspects(aspects, specifics):
    have = {k.lower(): v for k, v in specifics.items()}
    required = [a for a in aspects if a["required"]]
    recommended = [a for a in aspects if not a["required"] and a["usage"] == "RECOMMENDED"]
    missing = 0
    for label, group, show_values in (("REQUIRED", required, 25),
                                      ("RECOMMENDED", recommended, 10)):
        if not group:
            continue
        out(f"\n{label} item specifics:")
        for a in group:
            value = have.get(a["name"].lower())
            if isinstance(value, list):
                value = ", ".join(map(str, value))
            status = f"= {value}" if value else "MISSING"
            if not value and a["required"]:
                missing += 1
            kind = ("pick from list" if a["mode"] == "SELECTION_ONLY" else "free text") + \
                   (", multiple ok" if a["multi"] else "")
            out(f"  {a['name']}: {status}   [{kind}]")
            if not value and a["values"]:
                vals = a["values"][:show_values]
                more = f" ... (+{len(a['values']) - len(vals)} more)" if len(a["values"]) > len(vals) else ""
                out(f"      e.g. {' | '.join(vals)}{more}")
    return missing


def cmd_category(args):
    folder = _folder(args.folder)
    listing = lst.load_listing(folder)
    client = EbayClient(ebay_api.load_config())
    changed = False

    if args.id:
        listing["category_id"], listing["category_name"] = str(args.id), ""
        changed = True
    elif args.query or args.pick or not listing.get("category_id"):
        query = args.query or listing.get("title")
        if not query:
            raise EbayError("Give a --query (or set a title in listing.json first).")
        suggestions = client.category_suggestions(query)
        if not suggestions:
            raise EbayError(f'No category suggestions for "{query}". Try other words.')
        if args.pick:
            if not 1 <= args.pick <= len(suggestions):
                raise EbayError(f"--pick must be 1..{len(suggestions)}")
            cat_id, name, path = suggestions[args.pick - 1]
            listing["category_id"], listing["category_name"] = cat_id, path
            changed = True
        else:
            out(f'Category suggestions for "{query}":')
            for i, (cat_id, name, path) in enumerate(suggestions[:10], 1):
                out(f"  {i:>2}. [{cat_id}] {path}")
            out("\nChoose one:  python ebay_lister.py category FOLDER --pick N"
                + (f' --query "{args.query}"' if args.query else ""))
            return 0

    if changed:
        lst.save_listing(folder, listing)
    cat_id = listing["category_id"]
    out(f"Category: [{cat_id}] {listing.get('category_name') or ''}")

    required, conditions = client.condition_policy(cat_id)
    current = listing.get("condition_id")
    if conditions:
        out("\nAllowed conditions:")
        for cid, desc in conditions:
            out(f"  {'*' if cid == current else ' '} {cid}  {desc}")
        if current not in [c for c, _ in conditions]:
            out(f"  !! condition_id {current} is not allowed here - pick one above")
    elif not required:
        out("\nThis category doesn't use item condition (set condition_id to null).")

    missing = _print_aspects(client.item_aspects(cat_id), listing.get("item_specifics") or {})
    if missing:
        out(f"\n{missing} required item specific(s) missing - add them to "
            f'"item_specifics" in listing.json.')
    return 0


def cmd_comps(args):
    folder = _folder(args.folder)
    listing = lst.load_listing(folder)
    query = args.query or listing.get("title")
    if not query:
        raise EbayError("Give a --query (or set a title in listing.json first).")
    client = EbayClient(ebay_api.load_config())
    results, total = client.search_active(
        query,
        category_id=None if args.any_category else listing.get("category_id") or None,
        condition_id=None if args.any_condition else listing.get("condition_id"))

    out(f'Active fixed-price listings for "{query}": {total} found, {len(results)} priced')
    out("These are ASKING prices, not sold prices. For sold prices use Seller Hub >")
    out("Research (Terapeak) - eBay doesn't expose sold data to this kind of app.\n")
    if not results:
        out("Nothing found - try --query with fewer words, --any-condition or --any-category.")
        return 0
    prices = sorted(p for p, *_ in results)
    out(f"  low ${prices[0]:.2f}   median ${statistics.median(prices):.2f}   "
        f"high ${prices[-1]:.2f}   (n={len(prices)}, item price only, excl. shipping)\n")
    for price, cur, title, url in sorted(results)[:15]:
        out(f"  ${price:>9.2f}  {title[:70]}")
        out(f"             {url}")
    return 0


def _upload_photos(client, folder, listing, state):
    urls = []
    photos = lst.photo_paths(folder, listing)
    for i, path in enumerate(photos, 1):
        url = lst.cached_photo_url(state, client.env, path)
        if url:
            out(f"  photo {i}/{len(photos)} {path.name}: already uploaded")
        else:
            out(f"  photo {i}/{len(photos)} {path.name}: uploading...")
            url, expires = client.upload_photo(path)
            lst.remember_photo(state, client.env, path, url, expires)
            lst.save_state(folder, state)
        urls.append(url)
    return urls


def _verify(folder, listing, cfg, client, state):
    """Local checks, photo upload, VerifyAddItem. Returns (picture_urls, uuid) or None."""
    errors, warnings = lst.validate(folder, listing, cfg)
    for w in warnings:
        out(f"  warning: {w}")
    if errors:
        out("\nFix these in listing.json / config.json first:")
        for e in errors:
            out(f"  - {e}")
        return None

    state.setdefault("uuid", lst.new_uuid())
    lst.save_state(folder, state)
    out("Uploading photos to eBay:")
    urls = _upload_photos(client, folder, listing, state)

    out("\nChecking listing with eBay (VerifyAddItem - nothing is listed)...")
    root, ebay_warnings = client.trading(
        "VerifyAddItem", lst.build_item_xml("VerifyAddItem", listing, cfg, urls, state["uuid"]))
    for w in ebay_warnings:
        out(f"  eBay warning [{w['code']}]: {w['message']}")
    fees = ebay_api.parse_fees(root)
    listing_fee = [f for f in fees if f[0] == "ListingFee"]
    if listing_fee:
        out(f"  Listing fees: ${listing_fee[0][1]:.2f}")
    else:
        out("  Listing fees: $0.00")
    for name, amount, cur in fees:
        if name != "ListingFee":
            out(f"    {name}: ${amount:.2f}")
    out("  (Final value fees are charged only when it sells.)")
    return urls, state["uuid"]


def _summary(listing, n_photos):
    price = f"${float(listing['price']):.2f}"
    kind = "Buy It Now" if listing["listing_type"] == lst.FIXED else \
        f"Auction starting {price}, {listing['duration'].replace('Days_', '')} days"
    out(f"\n  Title:     {listing['title']}")
    out(f"  Price:     {price}  ({kind}{', best offer on' if listing.get('best_offer') else ''})")
    out(f"  Category:  [{listing['category_id']}] {listing.get('category_name') or ''}")
    out(f"  Condition: {listing.get('condition_id')}  {listing.get('condition_description') or ''}"[:200])
    out(f"  Photos:    {n_photos}")


def cmd_verify(args):
    folder = _folder(args.folder)
    cfg = ebay_api.load_config()
    client = EbayClient(cfg)
    listing, state = lst.load_listing(folder), lst.load_state(folder)
    if state.get("item_id"):
        out(f"Already listed: {state['url']}")
        return 0
    result = _verify(folder, listing, cfg, client, state)
    if not result:
        return 2
    _summary(listing, len(result[0]))
    out("\nPassed eBay's checks. To list it:  python ebay_lister.py publish FOLDER")
    return 0


def cmd_publish(args):
    folder = _folder(args.folder)
    cfg = ebay_api.load_config()
    client = EbayClient(cfg)
    listing, state = lst.load_listing(folder), lst.load_state(folder)
    if state.get("item_id"):
        out(f"Already listed: {state['url']}\nEdit it in Seller Hub; this tool won't list it twice.")
        return 0

    result = _verify(folder, listing, cfg, client, state)
    if not result:
        return 2
    urls, item_uuid = result
    _summary(listing, len(urls))
    if cfg["environment"] == "production":
        out("\nThis creates a LIVE listing on eBay.")
    if not args.yes:
        if not sys.stdin.isatty():
            out("Re-run with --yes to confirm.")
            return 2
        if input('Type LIST to publish: ').strip() != "LIST":
            out("Cancelled.")
            return 1

    try:
        root, warnings = client.trading(
            "AddItem", lst.build_item_xml("AddItem", listing, cfg, urls, item_uuid))
        item_id = root.findtext("ItemID")
    except EbayError as err:
        item_id = getattr(err, "duplicate_item_id", None)
        if not item_id:
            raise
        out("eBay says this item was already listed (earlier attempt went through).")
        warnings = []
    for w in warnings:
        out(f"  eBay warning [{w['code']}]: {w['message']}")

    url = f"{client.hosts['web']}/itm/{item_id}"
    state.update({"item_id": item_id, "url": url, "environment": client.env,
                  "listed_at": datetime.now().isoformat(timespec="seconds")})
    lst.save_state(folder, state)
    out(f"\nLISTED: {url}")
    return 0


def cmd_status(args):
    folder = _folder(args.folder)
    items = [folder] if (folder / lst.LISTING_FILE).exists() else \
        sorted((p for p in folder.iterdir() if (p / lst.LISTING_FILE).exists()),
               key=lambda p: lst.natural_key(p.name))
    if not items:
        out(f"No item folders (with {lst.LISTING_FILE}) under {folder}")
        return 0
    for item in items:
        listing, state = lst.load_listing(item), lst.load_state(item)
        price = listing.get("price")
        price = f"${float(price):.2f}" if isinstance(price, (int, float)) else "no price"
        where = state["url"] if state.get("item_id") else "draft"
        out(f"  {item.name:<28} {price:>10}  {(listing.get('title') or '(no title)')[:50]:<50}  {where}")
    return 0


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def build_parser():
    p = argparse.ArgumentParser(prog="ebay_lister.py",
                                description="Turn a folder of item photos into an eBay listing.")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("setup", help="create the config file").set_defaults(func=cmd_setup)

    a = sub.add_parser("auth", help="sign in to eBay (one time)")
    a.add_argument("--redirect-url", help="URL eBay redirected to after you clicked Agree")
    a.set_defaults(func=cmd_auth)

    a = sub.add_parser("policies", help="list / choose business policies")
    a.add_argument("--shipping")
    a.add_argument("--payment")
    a.add_argument("--return", dest="return_")
    a.set_defaults(func=cmd_policies)

    a = sub.add_parser("prep", help="prepare photos and create listing.json")
    a.add_argument("folder")
    a.set_defaults(func=cmd_prep)

    a = sub.add_parser("category", help="choose category, show required specifics")
    a.add_argument("folder")
    a.add_argument("--query", help="words describing the item (default: title)")
    a.add_argument("--pick", type=int, help="use suggestion number N")
    a.add_argument("--id", help="set a category ID directly")
    a.set_defaults(func=cmd_category)

    a = sub.add_parser("comps", help="active listings for price reference")
    a.add_argument("folder")
    a.add_argument("--query", help="search words (default: title)")
    a.add_argument("--any-condition", action="store_true")
    a.add_argument("--any-category", action="store_true")
    a.set_defaults(func=cmd_comps)

    a = sub.add_parser("verify", help="dry run with eBay (lists nothing)")
    a.add_argument("folder")
    a.set_defaults(func=cmd_verify)

    a = sub.add_parser("publish", help="create the live listing")
    a.add_argument("folder")
    a.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    a.set_defaults(func=cmd_publish)

    a = sub.add_parser("status", help="show drafted / listed items under a folder")
    a.add_argument("folder")
    a.set_defaults(func=cmd_status)
    return p


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):   # Windows consoles/pipes vs. odd titles
        sys.stdout.reconfigure(errors="replace")
    args = build_parser().parse_args(argv)
    try:
        return args.func(args) or 0
    except (EbayError, FileNotFoundError, RuntimeError) as err:
        out(f"ERROR: {err}")
        return 1
    except json.JSONDecodeError as err:
        out(f"ERROR: a JSON file has a syntax error ({err}). Fix listing.json / config.json.")
        return 1
    except requests.RequestException as err:
        out(f"ERROR: couldn't reach eBay ({err.__class__.__name__}). Check the connection.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
