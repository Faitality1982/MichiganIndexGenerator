# High Caliber Estate Sales LLC — Estate Sale Agreement

`High_Caliber_Estate_Sales_Agreement.docx` is a 4-page client-facing agreement
to conduct an estate sale. `build_contract.js` regenerates it.
`High_Caliber_Estate_Sales_Agreement.pdf` is a rendered preview.

## Logo

Drop the company logo in this directory as `logo.png` or `logo.jpg` and rebuild.
It is placed on the cover (scaled to 2.4 in wide) and in the running header on
pages 2+ (scaled to 0.31 in tall, so a tall logo cannot grow into the body).
Aspect ratio is read from the file, so the image is never distorted. With no
logo file present the wordmark falls back to type.

## Regenerating

```bash
npm install docx
node build_contract.js High_Caliber_Estate_Sales_Agreement.docx
```

## Form-field formatting

Fill-in rules are **bottom borders on borderless table cells**, not underlined
spaces. An underlined whitespace run gets trimmed at layout time and the rule
disappears — that is why the first draft rendered labels with no line after
them. Table borders always draw, and the cell width sets exactly how far the
rule runs, so every line reaches the right margin.

Short inline blanks inside a sentence (`_____%`, `$_______`, `Initial: ____`)
use literal underscore characters for the same reason.

Signature rows set `HeightRule.ATLEAST` (~0.32 in) so there is room to write.

## Pagination

Content flows continuously. There is exactly **one** forced break, on the
"Our business is built on referrals" paragraph, so the closing letter and the
whole signature block form a single unsplit signature page — without it the
block splits mid-way across two pages.

Never use a standalone `PageBreak` paragraph: when the preceding page is exactly
full, the break paragraph itself lands on a fresh page and emits a blank one.
Use `pageBreakBefore` on the paragraph that should start the page.

The company name repeats on pages 2+ via a real page `Header` with
`titlePage: true` (page 1 gets an empty first-page header, since it carries the
full letterhead). Earlier drafts faked this with inline heading paragraphs, which
forced a page break at every section and wasted roughly a page.

The body font is Calibri. When previewing on Linux, install
`fonts-crosextra-carlito` first; without a metric-compatible font the
substitute is wider and labels wrap that would not wrap in Word.

## Placeholders to fill before use

These appear in the letterhead on page 1 and must be replaced:

| Placeholder | Notes |
|---|---|
| `[ZIP]` | ZIP for 32055 Wilson Drive, Warren, MI |
| `[PHONE]` | Business phone |
| `[EMAIL]` | Business email |

Blank underscore fields in the body are intentional — they are filled in by hand
per sale (dates, address, commission percentages, cancellation fee, parking,
key/security codes, discount schedule).

## Terms left blank rather than pre-set

| Term | Where |
|---|---|
| Commission % on gross proceeds | p.2, Liquidator ¶7 |
| Commission % on titled property (vehicles, tractors, boats, trailers) | p.2, Liquidator ¶7 |
| Deduction % for items removed after work begins | p.2 and p.3, Seller ¶7 |
| Cancellation fee | p.4, Additional Terms |

## Execution

Both members sign for the Liquidator — William Faitel and Casey Faitel — each
with their own signature and date line, above the Seller's block.

## Structure

1. **Page 1** — Letterhead, sale dates, estate address, Liquidator duties 1–2,
   discount schedule by sale length.
2. **Page 2** — Liquidator duties 3–7: pricing authority, advertising, security,
   payment methods, net proceeds and commission, removed-item deduction.
3. **Page 3** — Seller duties 1–9: access, keys, NFS items, waiver, insurance,
   indemnification, no removal, photo release, HOA approval. Seller signature.
3. **Pages 3–4** — Additional terms: title, release on acceptance of proceeds,
   venue, cancellation, best-efforts disclaimer, weather, parking, client
   attendance, sale of real property.
4. **Page 4** — Referral/closing letter and the signature block: both
   Liquidator members, then the Seller.

## Venue clause

Set to the **37th District Court, City of Warren, Macomb County**, with Macomb
County Circuit Court as the alternative. Change this if the business relocates
or if counsel prefers a different forum.

## Note

This is a business form, not legal advice. Have a Michigan attorney review it
before putting it in front of clients — particularly the indemnification,
waiver-of-claims, cancellation-fee, and removed-item deduction provisions,
which are the clauses most likely to be contested.
