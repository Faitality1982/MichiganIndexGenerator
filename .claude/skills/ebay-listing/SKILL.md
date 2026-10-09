---
name: ebay-listing
description: Turn photos of an item into a live eBay listing or a ready-to-post Facebook Marketplace draft. Use when the user points you to photos or a photo folder and wants them listed, asks you to "list this" on eBay or Facebook, or wants a batch of estate-sale items put up. Covers deciding eBay vs Facebook, drafting the title, description, item specifics and condition from the photos, picking the category, checking prices, and publishing through ebay_lister.
---

# eBay or Facebook listing from photos

You write the listing; `ebay_lister/ebay_lister.py` (in this repo) does everything that talks to eBay and decides eBay versus Facebook Marketplace from the numbers you give it. Facebook has no listing API for individual sellers, so a Facebook item ends as a draft folder the user posts in the Meta Seller app (phone or web). Do all the judgment here in Claude Code; never add calls to a paid AI API to the tool, because the user runs this on their Claude subscription. Run it with `python` (or `py` on Windows if `python` isn't found). Setup and command details are in `ebay_lister/README.md`.

Publishing creates a public listing on the user's real eBay account and can incur fees. Never run `publish --yes` until the user has approved that specific item's final summary in this conversation.

## Before the first item

Skip this for items that route to Facebook; `route` and `facebook` work without the eBay setup. For eBay items, run `python ebay_lister/ebay_lister.py policies`. It's read-only and needs both the config and the eBay sign-in. If it errors with "No config found", "Missing client_id" or "Not signed in", stop and walk the user through the one-time setup in `ebay_lister/README.md`. They have to do the eBay sign-in step themselves, because it happens in their browser. If no policy is marked `*` as configured, have them choose one of each.

## Per item

The user gives you a folder with one item's photos in it. If they give you loose photos instead, ask them to put the photos in their own folder (one folder per item).

1. **Prep the photos.** Run `python ebay_lister/ebay_lister.py prep "<folder>"`. It writes upright, resized JPEGs to `<folder>/prepared/` with GPS and other metadata removed, and creates a `listing.json` template.
2. **Look at every photo** in `prepared/` with the Read tool. Zoom in mentally on labels, maker's marks, model and serial plates, signatures, tags, and damage. If something that matters is unreadable (a hallmark, a model number), ask for a close-up. Don't guess.
3. **Draft `listing.json`** using the rules below. Put anything you couldn't confirm into `seller_notes`.
4. **Route it.** Fill the `routing` block (see below), then run `route "<folder>"`. It prints eBay, Facebook, or ASK THE USER with the numbers behind it. Tell the user the result in a sentence. On ASK, give both nets and your recommendation, let the user choose, and set `routing.decision` to `"ebay"` or `"facebook"`. The user can always overrule the rule: set `routing.decision` to what they want.
   - **Facebook:** fill the `facebook` block, run `facebook "<folder>"`, and show the user the draft it prints. It writes `<folder>/facebook/listing.txt` and numbered photos (cover first, at most 10). Then tell them to post it in the Seller app. You're done with this item; skip the steps below.
   - **eBay:** carry on with step 5.
5. **Pick a category.** Run `category "<folder>" --query "<3-6 words: what it is>"`, choose the best match, then `category "<folder>" --pick N`. The output lists the allowed conditions and the required and recommended item specifics. Fill every REQUIRED specific. For "pick from list" specifics, use one of eBay's values exactly as printed. Fill recommended ones only when the photos or the user support them. Rerun `category "<folder>"` until nothing required shows as MISSING.
6. **Check prices.** Run `comps "<folder>"`. It shows active asking prices, not sold prices. Tell the user the low, median and high. If they want a suggestion, give one and explain it, and say it is based on asking prices. Mention that Seller Hub > Research (Terapeak) shows sold prices. The user decides the price. Don't write a price into `listing.json` until they give it or agree to yours.
7. **Resolve `seller_notes`** by asking the user. Update the draft with their answers, then empty the list.
8. **Verify.** Run `verify "<folder>"`. This uploads the photos and has eBay check the listing without listing it. It also shows the insertion fee. Fix any errors and rerun until it passes.
9. **Get approval.** Show the user the title, price and format, category, condition and condition note, item specifics, a short version of the description, the photo count, and the fees. Ask whether to list it.
10. **Publish** only after the user says yes: `publish "<folder>" --yes`. Give them the listing URL it prints.

For a batch (a parent folder containing one subfolder per item), do steps 1-8 for each item (steps 1-4 for Facebook items), then run `status "<parent>"` and show the table. Publish only the items the user approves. "List them all" counts as approval for every item in the table they just saw.

## listing.json

```json
{
  "title": "Stiffel Brass Table Lamp 3-Way Pleated Shade 31 in",
  "category_id": "",
  "category_name": "",
  "condition_id": 3000,
  "condition_description": "Tested and working. Light tarnish on the base; small crease in the shade. See photos.",
  "item_specifics": {"Brand": "Stiffel", "Type": "Table Lamp", "Features": ["3-Way", "Dimmable"]},
  "description_html": "<p>...</p>",
  "price": 85.00,
  "best_offer": true,
  "listing_type": "FixedPriceItem",
  "duration": "GTC",
  "quantity": 1,
  "sku": "",
  "photos": [],
  "seller_notes": ["Height not visible in photos. Need a measurement."]
}
```

- `photos`: leave empty to use every prepared photo in filename order. To reorder or drop photos, list the `prepared/` filenames in the order you want. The first photo is the gallery image, so choose the clearest full shot of the whole item. Maximum 24.
- Auctions: `"listing_type": "Chinese"`, `"duration": "Days_7"` (also Days_1/3/5/10), and `price` is the starting bid. Default to fixed price unless the user asks for an auction.
- `category_id` and `category_name` are filled by the `category` command.
- `seller_notes` is never sent to eBay.

## Routing (eBay or Facebook)

```json
"routing": {
  "weight_lb": 4,
  "dims_in": [14, 10, 8],
  "local_only": "",
  "ebay_price_est": 120,
  "ship_cost_est": 15,
  "free_shipping": false,
  "local_price_est": 40,
  "decision": ""
}
```

- `weight_lb` and `dims_in` are the packed size. Use the user's measurements when they gave them; otherwise estimate, and say so when you report the route.
- `local_only`: a short reason when it can't ship sensibly at all (refrigerator, washer, sofa, piano, glass tabletop). Leave it empty otherwise.
- `ebay_price_est`: base it on `comps` when eBay setup is done (asking prices, so lean low), otherwise on what you know, and say which.
- `ship_cost_est`: a rough label cost for that weight and size. `free_shipping` is true only if the user's shipping policy is free shipping.
- `local_price_est`: what it would realistically sell for on Facebook locally. Facebook has no price data, so this is your estimate; say so.

The rules, in order: local-only, over 70 lb, or over 130 in length + girth goes to Facebook. eBay netting under $25 goes to Facebook. eBay wins when its net (after about 13.6% plus $0.40 in fees, and shipping if free) beats the local price by $15 or 25%, whichever is more. eBay ahead by less than that is ASK; otherwise Facebook. The thresholds and fee rate can be changed in config.json under `"routing"`.

## Facebook draft

```json
"facebook": {
  "title": "",
  "price": null,
  "condition": "Used - Good",
  "category": "Appliances",
  "description": ""
}
```

- `condition` is required: New, Used - Like New, Used - Good, or Used - Fair.
- Blank `title`, `price` and `description` fall back to the eBay title, `routing.local_price_est`, and the eBay description as plain text. Write a separate `description` when the eBay one talks about shipping or reads too formally for a local sale. Mention pickup for local-only items.
- The drafting rules below apply to Facebook text too.

## Drafting rules

The user sells estate-sale items and wants accurate listings, even if that means understating. Every claim has to come from the photos or from the user.

**Never assert without evidence.** That includes maker or brand attribution, age or era ("antique", "vintage", "1950s"), material ("sterling", "solid gold", "real wood", "crystal"), authenticity ("genuine", "signed", "original"), rarity, value, and working condition. If a mark is visible, describe what it says: "marked STERLING on the base", "signed 'R. Lee' lower right". If the user tells you something, use it as fact. If you only suspect something, put it in `seller_notes` and ask.

**Measurements come from the user.** Photos can't give reliable dimensions. Ask for them for anything where size matters, which is most things.

**Working condition.** For anything electrical or mechanical, ask whether it was tested. If it wasn't, say "Untested" in the description and condition note, and suggest condition 7000 (For parts or not working). Listing an untested item as Used invites "not as described" returns.

**Title** (80 characters maximum). Order: brand or maker, then model or pattern, then item type, then key attributes (material, color, size, count). Use the words buyers type into search. No ALL CAPS, no "L@@K", no "rare", "wow" or "nice", no repeated keywords, no emoji. Don't claim anything the rules above forbid.

**Condition.** Use a condition ID from the `category` output. These are common, but the allowed set depends on the category:

| ID | Condition |
|----|-----------|
| 1000 | New |
| 1500 | New other (open box, no tags) |
| 3000 | Used |
| 7000 | For parts or not working |

Books, media and some collectibles use 4000 Very Good, 5000 Good and 6000 Acceptable instead of 3000. A few categories, such as some Antiques categories, take no condition: set `condition_id` to `null`. For anything that isn't new, `condition_description` should name every flaw you can see (chips, cracks, stains, scratches, missing parts, repairs) and end with "See photos."

**Item specifics.** Use eBay's names exactly as the `category` command prints them. Use "Unbranded" for Brand only when there's no mark at all. For MPN or Model when there isn't one, use "Does Not Apply". Never invent a model number.

**Description HTML.** Keep it simple and mobile-friendly:

```html
<p>One or two sentences: what it is, who made it (if marked), and what stands out.</p>
<ul>
  <li><b>Maker:</b> Stiffel (label on the socket)</li>
  <li><b>Material:</b> brass body, fabric shade</li>
  <li><b>Dimensions:</b> 31 in tall, shade 18 in wide (measured)</li>
  <li><b>Markings:</b> ...</li>
</ul>
<p><b>Condition:</b> the same facts as the condition note. Please see all photos. They are part of the description.</p>
```

- No scripts, iframes, forms, external links or images, and no contact details or off-eBay payment wording. eBay strips or blocks these.
- Shipping, returns and payment come from the user's business policies. Don't restate them. Any standard footer is added from the config automatically.
- Don't copy text from other sellers' listings you saw in `comps`.
