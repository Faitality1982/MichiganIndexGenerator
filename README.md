# High Caliber Tote Racks

A side service for High Caliber Estate Sales: custom 2x4 storage racks for 27-gallon totes, built as wall installs or mobile racks on casters, with optional finish and totes supplied.

Started October 11, 2026. Status: planning. No jobs quoted yet.

## What's in here

| Path | What it is |
|---|---|
| `calculator/index.html` | The quote calculator. Open it in any browser (double-click on Windows). Builds the customer quote PDF and the internal shop sheet. |
| `docs/pricing.md` | Price sheet, how each number was set, worked examples, margins. |
| `docs/build-spec.md` | Rack design, dimensions, the lumber takeoff math, cut lists for the two standard builds. |
| `docs/finishing.md` | Clear seal, stain, and paint: process, pricing, cold-weather rules. |
| `docs/sourcing.md` | Where to buy totes and lumber, brand fit problems, prices seen. |
| `docs/business-notes.md` | Who buys this, how it fits the estate sale business, insurance and tax questions. |
| `docs/open-questions.md` | Everything still unverified. Work this list before the first job. |

## Calculator

Two ways to use it:

1. **In Claude** (private link, works on the phone): [Tote Rack Quote artifact](https://claude.ai/artifact/1KjaxyD5RXYugJGVnwHNsw). "Save quote PDF" opens the phone's share sheet so the PDF can go straight into an email.
2. **From this repo**: open `calculator/index.html` in Chrome or Edge. "Save quote PDF" downloads the file. Needs an internet connection the first time for the PDF library and fonts.

All prices, costs, lumber prices, and labor rates live under **Pricing & cost settings** on the page. Changes save in that browser only, so set them on each device you use, or edit the `DEFAULTS` block near the top of the script in `index.html` and commit it.

Features:

- Rack size from 1 to 8 totes wide, 2 to 6 high
- Wall install or mobile on locking casters
- Customer's totes or HDX totes supplied
- Finish: raw, clear seal, stain + seal, paint (with color)
- Delivery fee, discount/adjustment line, job notes
- Customer quote with a to-scale front drawing, line items, deposit, terms
- Shop sheet: cost, profit, hours, dollars per hour, cut list, shopping list, warnings

## Starting price (summary)

- **$395** wall rack, up to 12 slots, customer's totes
- **+$20** per slot over 12
- **+$75** mobile base with casters
- **+$14** per HDX tote we supply
- Finish adds a setup fee plus a per-slot charge (see `docs/finishing.md`)

Standard builds:

| Build | Customer's totes | We supply totes | Paint added |
|---|---|---|---|
| Mobile 3 wide x 4 high (12) | $470 | $638 | +$220 |
| Wall 6 wide x 5 high (30) | $755 | $1,175 | +$400 |
