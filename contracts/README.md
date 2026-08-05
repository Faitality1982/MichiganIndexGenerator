# High Caliber Estate Sales LLC — Estate Sale Agreement

`High_Caliber_Estate_Sales_Agreement.docx` is a 5-page client-facing agreement
to conduct an estate sale. `build_contract.js` regenerates it.

## Regenerating

```bash
npm install docx
node build_contract.js High_Caliber_Estate_Sales_Agreement.docx
```

## Placeholders to fill before use

These appear in the letterhead on page 1 and must be replaced:

| Placeholder | Notes |
|---|---|
| `[ZIP]` | ZIP for 32055 Wilson Drive, Warren, MI |
| `[PHONE]` | Business phone |
| `[EMAIL]` | Business email |
| `[OWNER NAME]` | Owner / managing member |

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

## Structure

1. **Page 1** — Letterhead, sale dates, estate address, Liquidator duties 1–2,
   discount schedule by sale length.
2. **Page 2** — Liquidator duties 3–7: pricing authority, advertising, security,
   payment methods, net proceeds and commission, removed-item deduction.
3. **Page 3** — Seller duties 1–9: access, keys, NFS items, waiver, insurance,
   indemnification, no removal, photo release, HOA approval. Seller signature.
4. **Page 4** — Additional terms: title, release on acceptance of proceeds,
   venue, cancellation, best-efforts disclaimer, weather, parking, client
   attendance, sale of real property.
5. **Page 5** — Referral/closing letter and full signature block.

## Venue clause

Set to the **37th District Court, City of Warren, Macomb County**, with Macomb
County Circuit Court as the alternative. Change this if the business relocates
or if counsel prefers a different forum.

## Note

This is a business form, not legal advice. Have a Michigan attorney review it
before putting it in front of clients — particularly the indemnification,
waiver-of-claims, cancellation-fee, and removed-item deduction provisions,
which are the clauses most likely to be contested.
