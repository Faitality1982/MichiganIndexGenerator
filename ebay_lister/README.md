# eBay Lister

Turns a folder of item photos into a live eBay listing on your account, or into a Facebook Marketplace draft when the item sells better locally.

In Claude Code you say *"List the item in `listings\brass-lamp`"*. Claude looks at the photos and writes the title, description, item specifics and condition. It picks the category, checks prices against active listings, asks you about anything it can't confirm from the photos, and has eBay dry-run the listing so you can see the fees. It lists the item only after you approve it. The workflow is in the `ebay-listing` skill (`.claude/skills/ebay-listing/SKILL.md`). This folder holds the tool that does the eBay side.

Listings are created with eBay's Trading API, so they're ordinary listings you can revise, end or relist in Seller Hub.

## Requirements

- Python 3.9+ (Windows, macOS or Linux)
- `pip install -r requirements.txt`
- For iPhone `.HEIC` photos: `pip install pillow-heif`
- An eBay seller account with business policies (Seller Hub > Account > Business policies). Most accounts already have them.

## One-time setup (about 20 minutes)

### 1. Get eBay API keys

1. Create a free developer account at <https://developer.ebay.com> and sign in.
2. Go to **Application Keysets** and create a **Production** keyset. Before eBay turns production keys on, it asks how you handle *Marketplace Account Deletion* notifications. This tool stores no data about other eBay users, so choose the exemption option. The exact wording on eBay's page may differ.
3. Copy the **App ID (Client ID)** and **Cert ID (Client Secret)**. You don't need the Dev ID.
4. On the same keyset, open **User Tokens**, then **Get a Token from eBay via Your Application**, then **Add eBay Redirect URL**. Leave the accepted/declined URLs at eBay's defaults and save. Copy the **RuName**. It's a long ID, not a URL, and looks like `Your_Name-YourName-MyApp-PRD-abc123`.

### 2. Configure

```
cd ebay_lister
python ebay_lister.py setup
```

This creates `%USERPROFILE%\.ebay_lister\config.json` (`~/.ebay_lister/` on Mac/Linux). The file is outside the repo, so your keys can't be committed by accident. Fill in:

| Field | Value |
|---|---|
| `client_id`, `client_secret`, `ru_name` | from step 1 |
| `postal_code` | ZIP the items ship from, e.g. `48060` |
| `location` | e.g. `Port Huron, MI` |
| `description_footer_html` | optional; added to the end of every description |

### 3. Sign in to eBay

```
python ebay_lister.py auth
```

Open the URL it prints and sign in with your **seller** account. After you click **Agree**, eBay shows a confirmation page. Copy that page's full address from the browser bar and paste it into the terminal. The code in it expires in about 5 minutes. The sign-in stays valid for about 18 months; after that, run `auth` again.

### 4. Choose business policies

```
python ebay_lister.py policies
python ebay_lister.py policies --shipping 1234567890 --payment 2345678901 --return 3456789012
```

The first command lists your shipping, payment and return policies with their IDs. The second saves the ones you pick; every listing uses them.

### Optional: try it in the sandbox first

eBay's sandbox is a fake marketplace for testing. Create a **Sandbox** keyset and a sandbox test user at developer.ebay.com, set `"environment": "sandbox"` with the sandbox keys, then run `auth` and `policies` again. The sandbox's category suggestions and price data are thin, so use `category --id` there if you need to. Set it back to `"production"` when you're done.

## Using it

Put each item's photos in its own folder. `listings/` in this repo is git-ignored, so `listings\<item-name>\` is a convenient place. Then either ask Claude Code to list it, or run the steps yourself:

```
python ebay_lister.py prep      ..\listings\brass-lamp    # resize, rotate, strip GPS, create listing.json
  (write listing.json: title, description, specifics, condition, price)
python ebay_lister.py category  ..\listings\brass-lamp --query "brass table lamp"
python ebay_lister.py category  ..\listings\brass-lamp --pick 1
python ebay_lister.py comps     ..\listings\brass-lamp    # active asking prices
python ebay_lister.py verify    ..\listings\brass-lamp    # eBay dry run: errors + fees, lists nothing
python ebay_lister.py publish   ..\listings\brass-lamp    # asks you to type LIST
python ebay_lister.py status    ..\listings               # every item: draft or listed + URL
```

What ends up in an item folder:

```
brass-lamp\
    IMG_4471.HEIC ...     your originals (never modified)
    prepared\             web-ready JPEGs: long side at most 1600px, no EXIF/GPS
    listing.json          the listing
    ebay_state.json       managed by the tool: uploaded photo URLs, ItemID
    facebook\             Facebook draft: listing.txt + 01.jpg, 02.jpg ...
```

## eBay or Facebook Marketplace

After drafting `listing.json`, Claude fills its `routing` block (packed weight and size, eBay and local price estimates, shipping cost) and runs:

```
python ebay_lister.py route     ..\listings\fridge       # eBay, Facebook, or ask you
python ebay_lister.py facebook  ..\listings\fridge       # Facebook draft: facebook\listing.txt + photos
```

- Local only, over 70 lb, or over 130 in length + girth: Facebook.
- eBay would net under $25: Facebook.
- eBay net (after about 13.6% + $0.40 in fees, and shipping if you offer it free) beats the local price by $15 or 25%, whichever is more: eBay. Closer than that, Claude asks you.

Facebook doesn't offer a listing API to individual sellers, so the Facebook step stops at a draft: open the Meta Seller app (phone or web), start a listing, add the photos from `facebook\` in order, and paste the fields from `listing.txt`. `route` and `facebook` don't need the eBay setup.

The fee rate is approximate. Check it against eBay's fee page and change it, or any threshold, in `config.json`:

```json
"routing": {"ebay_fee_rate": 0.136, "ebay_fee_per_order": 0.40, "max_ship_weight_lb": 70,
            "max_ship_length_girth_in": 130, "min_ebay_net": 25, "ebay_margin_abs": 15,
            "ebay_margin_pct": 0.25, "fb_max_photos": 10}
```

eBay listings that offer shipping can also show up on Facebook Marketplace automatically, with checkout on eBay, so eBay items get Facebook buyers too.

## Good to know

- **Fees.** `verify` shows the insertion and upgrade fees eBay reports. Final value fees are charged only when the item sells.
- **No double listings.** Each item gets a unique ID that eBay uses to reject duplicates. If `publish` loses its connection partway through, running it again won't list the item twice. Once an item is listed, `publish` refuses to run on it again.
- **Price data.** `comps` shows active asking prices. eBay doesn't give this kind of app access to sold prices; use Seller Hub > Research (Terapeak) for those.
- **Photos.** Photos have to be on the computer running Claude Code. For phone photos, sync the camera roll (OneDrive, iCloud for Windows, Google Photos) or copy them over, then move each item's photos into its own folder.
- **Environment variables.** `EBAY_CLIENT_ID`, `EBAY_CLIENT_SECRET`, `EBAY_RUNAME` and `EBAY_REFRESH_TOKEN` override the config file. `EBAY_LISTER_HOME` moves the config folder.

## Tests

```
python -m unittest discover -s tests
```

The tests run offline against a fake eBay. They cover photo prep, validation, request XML, response parsing, and a full prep → category → verify → publish run.
