const fs = require('fs');
const path = require('path');
const {
  Document, Packer, Paragraph, TextRun, AlignmentType,
  PageOrientation, BorderStyle, UnderlineType, ImageRun,
  Footer, Header, PageNumber, Table, TableRow, TableCell, WidthType, VerticalAlign, HeightRule,
} = require('docx');

// ---------- logo ----------
// Drop the company logo next to this script as logo.png / logo.jpg and it is used
// on the cover and in the running header. Without it, the wordmark is set in type.
const LOGO_PATH = ['logo.png', 'logo.jpg', 'logo.jpeg']
  .map((f) => path.join(__dirname, f))
  .find((f) => fs.existsSync(f));

// Intrinsic pixel size, so the logo is scaled to width without distorting it.
function imageSize(buf, ext) {
  if (ext === 'png') {
    return { w: buf.readUInt32BE(16), h: buf.readUInt32BE(20) };
  }
  let i = 2; // JPEG: walk the segment chain to the SOF marker
  while (i < buf.length) {
    if (buf[i] !== 0xff) { i++; continue; }
    const marker = buf[i + 1];
    if (marker >= 0xc0 && marker <= 0xcf && ![0xc4, 0xc8, 0xcc].includes(marker)) {
      return { h: buf.readUInt16BE(i + 5), w: buf.readUInt16BE(i + 7) };
    }
    i += 2 + buf.readUInt16BE(i + 2);
  }
  return null;
}

const logo = (() => {
  if (!LOGO_PATH) return null;
  const ext = path.extname(LOGO_PATH).slice(1).toLowerCase();
  const data = fs.readFileSync(LOGO_PATH);
  const size = imageSize(data, ext === 'jpeg' ? 'jpg' : ext);
  if (!size) return null;
  return { data, type: ext === 'jpeg' ? 'jpg' : ext, aspect: size.h / size.w };
})();

// Logo scaled to a target width in pixels (96 px = 1 inch).
const logoRun = (widthPx) =>
  new ImageRun({
    data: logo.data,
    type: logo.type,
    transformation: { width: widthPx, height: Math.round(widthPx * logo.aspect) },
  });

// Logo constrained by height — used in the running header, where an unexpectedly
// tall logo would otherwise grow down into the body text.
const logoRunH = (heightPx) =>
  new ImageRun({
    data: logo.data,
    type: logo.type,
    transformation: { width: Math.round(heightPx / logo.aspect), height: heightPx },
  });

const FONT = 'Calibri';
const BODY = 21;          // 10.5pt
const CONTENT_W = 10540;  // 12240 page - 850 - 850 margins

// ---------- run helpers ----------
const t = (text, opts = {}) => new TextRun({ text, font: FONT, size: opts.size || BODY, ...opts });
const b = (text, opts = {}) => t(text, { bold: true, ...opts });
const checkbox = () => new TextRun({ text: '☐  ', font: 'Segoe UI Symbol', size: 22 });

// Non-breaking spaces so the underline actually renders — Word and LibreOffice
// both trim trailing ordinary spaces, which erases an underlined run.
const nb = (n) => ' '.repeat(n);
// Short inline blanks use literal underscores: an underlined whitespace run gets
// trimmed at layout time and the rule vanishes. Full-width fields use table borders.
const us = (n) => '_'.repeat(n);
const ul = (n) => t(us(n));

// ---------- paragraph helpers ----------
const P = (children, opts = {}) =>
  new Paragraph({
    children,
    spacing: {
      after: opts.after === undefined ? 105 : opts.after,
      before: opts.before,
      line: 246,
    },
    alignment: opts.alignment,
    indent: opts.indent,
    keepNext: opts.keepNext,
    pageBreakBefore: opts.pageBreakBefore,
    border: opts.border,
  });

const p = (text, opts = {}) => P([t(text, opts)], opts);

const clause = (num, runs, opts = {}) =>
  new Paragraph({
    children: [b(num + ') '), ...runs],
    spacing: { after: opts.after === undefined ? 122 : opts.after, line: 246 },
    indent: { left: 360, hanging: 360 },
  });

const initialLine = () =>
  new Paragraph({
    children: [b('Initial: '), b(us(22))],
    spacing: { after: 125, line: 246 },
    indent: { left: 360 },
  });

const sectionHeading = (text) =>
  new Paragraph({
    children: [b(text, { size: 24 })],
    spacing: { before: 120, after: 105 },
    keepNext: true,
  });

const rule = (after) =>
  new Paragraph({
    children: [t('')],
    border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: '000000', space: 1 } },
    spacing: { after: after === undefined ? 140 : after },
  });


// ---------- form-field tables ----------
// A borderless table; cells flagged `line` get a bottom border, which produces a
// straight rule that runs the full width of its column.
const NO_BORDER = { style: BorderStyle.NONE, size: 0, color: 'FFFFFF' };
const noBorders = {
  top: NO_BORDER, bottom: NO_BORDER, left: NO_BORDER, right: NO_BORDER,
  insideHorizontal: NO_BORDER, insideVertical: NO_BORDER,
};

const cell = (width, children, opts = {}) =>
  new TableCell({
    width: { size: width, type: WidthType.DXA },
    borders: opts.line
      ? { ...noBorders, bottom: { style: BorderStyle.SINGLE, size: 6, color: '000000' } }
      : noBorders,
    verticalAlign: VerticalAlign.BOTTOM,
    margins: { top: 20, bottom: 20, left: 0, right: opts.right === undefined ? 100 : opts.right },
    children,
  });

const labelCell = (width, text) =>
  cell(width, [new Paragraph({ children: [b(text)], spacing: { after: 0, line: 240 } })]);

const lineCell = (width) =>
  cell(width, [new Paragraph({ children: [t('')], spacing: { after: 0, line: 240 } })], { line: true });

// rows: array of arrays of {label, w} / {line, w}
const fieldTable = (rows, colWidths, opts = {}) =>
  new Table({
    columnWidths: colWidths,
    width: { size: CONTENT_W, type: WidthType.DXA },
    borders: noBorders,
    rows: rows.map(
      (cells) =>
        new TableRow({
          height: opts.height
            ? { value: opts.height, rule: HeightRule.ATLEAST }
            : undefined,
          children: cells.map((c) =>
            c.label !== undefined ? labelCell(c.w, c.label) : lineCell(c.w)
          ),
        })
    ),
  });

const spacer = (h) => new Paragraph({ children: [t('')], spacing: { after: h === undefined ? 120 : h, line: 120 } });

// ---------- letterhead ----------
const ctr = (text, opts) =>
  new Paragraph({
    children: [t(text, opts)],
    alignment: AlignmentType.CENTER,
    spacing: { after: opts && opts.after !== undefined ? opts.after : 30, line: 240 },
  });

const letterhead = [
  ...(logo
    ? [
        new Paragraph({
          // Sized by the larger dimension: a square mark lands ~1.6in, a wide
          // banner ~2.4in, so neither shape dominates the cover.
          children: [logo.aspect > 0.5 ? logoRunH(155) : logoRun(230)],
          alignment: AlignmentType.CENTER,
          spacing: { after: 60 },
        }),
      ]
    : [ctr('HIGH CALIBER ESTATE SALES LLC', { bold: true, size: 36, after: 30 })]),
  ctr('Professional Estate Liquidation — Serving Metro Detroit', { size: 19, italics: true, after: 55 }),
  ctr('32055 Wellston Dr, Warren, MI 48093', { size: 19 }),
  ctr('Phone: (586) 246-8620   •   contact@highcaliberestatesales.com', { size: 19 }),
  ctr('highcaliberestatesales.com', { size: 19 }),
  ctr('William Faitel  •  Casey Faitel, Members', { size: 19, after: 80 }),
  rule(90),
];

// Repeating page header for pages 2+ (page 1 carries the full letterhead).
const pageHeader = () =>
  new Header({
    children: [
      new Paragraph({
        children: logo ? [logoRunH(logo.aspect > 0.5 ? 42 : 30)] : [b('HIGH CALIBER ESTATE SALES LLC', { size: 22 })],
        alignment: AlignmentType.CENTER,
        spacing: logo ? { after: 20 } : { after: 20, line: 240 },
      }),
      rule(0),
    ],
  });

// Footer: appears on every page, page 1 included.
const pageFooter = () =>
  new Footer({
    children: [
      new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { before: 100 },
        children: [
          t('High Caliber Estate Sales LLC — Agreement to Conduct Estate Sale     Seller Initials: ', { size: 15 }),
          t(us(9), { size: 15 }),
          t('     Page ', { size: 15 }),
          new TextRun({ children: [PageNumber.CURRENT], font: FONT, size: 15 }),
          t(' of ', { size: 15 }),
          new TextRun({ children: [PageNumber.TOTAL_PAGES], font: FONT, size: 15 }),
        ],
      }),
    ],
  });

// ---------- body ----------
const body = [];

// ===== PAGE 1 =====
body.push(...letterhead);
body.push(ctr('AGREEMENT TO CONDUCT ESTATE SALE', { bold: true, size: 27, after: 150 }));

body.push(fieldTable(
  [
    [{ label: 'Start Date of Services:', w: 2950 }, { line: true, w: 7490 }],
    [{ label: 'Date(s) of Sale:', w: 2950 }, { line: true, w: 7490 }],
  ],
  [2950, 7490]
));
body.push(spacer(70));

body.push(p('Thank you for selecting High Caliber Estate Sales LLC to liquidate the contents of the estate known as:', { after: 110 }));

body.push(fieldTable(
  [
    [{ label: 'Address:', w: 1150 }, { line: true, w: 9290 }],
  ],
  [1150, 9290]
));
body.push(fieldTable(
  [
    [
      { label: 'City:', w: 750 }, { line: true, w: 4300 },
      { label: 'State:', w: 900 }, { line: true, w: 1400 },
      { label: 'Zip:', w: 640 }, { line: true, w: 2450 },
    ],
  ],
  [750, 4300, 900, 1400, 640, 2450]
));
body.push(spacer(90));

body.push(P([b('The Estate Sale will be held ON SITE.', { underline: { type: UnderlineType.SINGLE } })], { after: 110 }));

body.push(P([
  t('High Caliber Estate Sales LLC (also referred to in this Agreement as the ', { italics: true, bold: true }),
  t('"Liquidator"', { italics: true, bold: true }),
  t(') shall provide the following services in connection with the sale of the personal property located at the premises of the estate:', { italics: true, bold: true }),
], { after: 110 }));

body.push(sectionHeading('THE LIQUIDATOR SHALL:'));

body.push(clause('1', [
  t('Sort, organize, arrange, and display all items to be sold. If, during that process, we encounter items that appear to be of unusual value or of special sentimental value that you have not told us about, we will consult with you before pricing or selling them. We will use the tables, shelves, cabinets, and similar surfaces available at the premises for display, and we will supply any additional display equipment we consider necessary. The Liquidator will gather and dispose of unsold items that cannot be sold, using ordinary garbage pickup where possible. If the volume or size of the discarded items exceeds ordinary pickup, the Liquidator will arrange for a dumpster and the Seller will pay the dumpster cost.'),
], { after: 110 }));
body.push(initialLine());

body.push(p('The Liquidator will clean and polish selected items being sold — such as silverware, fine china, furniture, and similar goods — where doing so is necessary to present them well.', { after: 110 }));

body.push(P([
  b('We do NOT clean the home, windows, floors, walls, carpeting, or similar surfaces after the sale has concluded, and we cannot be held liable for soiled or worn flooring.', { underline: { type: UnderlineType.SINGLE } }),
], { after: 100 }));
body.push(initialLine());

body.push(P([b('If you would like our staff to wear shoe covers (booties) during the sale, initial here:')], { after: 100 }));
body.push(initialLine());

body.push(clause('2', [
  t('Price the property using tags, labels, or signs. During the course of the Estate Sale the Liquidator shall have full authority to negotiate prices with customers.'),
], { after: 120 }));

body.push(P([b('The number of days your sale runs determines the discount schedule:')], { after: 100 }));

const dayLine = (label, text) => new Paragraph({
  children: [checkbox(), b(label), t(text)],
  spacing: { after: 60, line: 240 },
  indent: { left: 720, hanging: 360 },
});

body.push(dayLine('One-day sale: ', 'Full price / half way through the sale day, 25% off.'));
body.push(dayLine('Two-day sale: ', 'Day One = full price / Day Two = 50% off and a $5 bag.'));
body.push(dayLine('Three-day sale: ', 'Day One = full price / Day Two = 25% off / Day Three = 50% off and a $5 bag.'));
body.push(dayLine('Four-day sale: ', 'Day One = full price / Day Two = 25% off / Day Three = 50% off / Day Four = 75% off and a $5 bag.'));
body.push(new Paragraph({
  children: [checkbox(), b('Custom discount schedule:')],
  spacing: { after: 90, line: 240 },
  indent: { left: 720, hanging: 360 },
}));

body.push(new Table({
  columnWidths: [1220, 1210, 1220, 1210, 1430, 1000, 1220, 1210],
  width: { size: CONTENT_W, type: WidthType.DXA },
  borders: noBorders,
  indent: { size: 720, type: WidthType.DXA },
  rows: [new TableRow({
    children: [
      labelCell(1220, 'Day One:'), lineCell(1210),
      labelCell(1220, 'Day Two:'), lineCell(1210),
      labelCell(1430, 'Day Three:'), lineCell(1000),
      labelCell(1220, 'Day Four:'), lineCell(1210),
    ],
  })],
}));
body.push(spacer(90));
body.push(initialLine());

// ===== PAGE 2 =====
body.push(clause('3', [
  t('The Seller shall '),
  b('NOT', { underline: { type: UnderlineType.SINGLE } }),
  t(' change the price of any item. The Liquidator reserves the right to remove items from the premises for research, appraisal, or safekeeping, and to lock up small or high-value items. Any such item will be priced in the best interest of the Seller.'),
], { after: 110 }));
body.push(initialLine());

body.push(clause('4', [
  t('Advertise the Estate Sale at the Liquidator’s expense through EstateSales.net, Facebook, Instagram, neighborhood apps, and selected local newspapers. The Liquidator will also place signs in the yard during the sale and additional directional signs in the vicinity of the sale where permitted by local ordinance.'),
], { after: 110 }));
body.push(initialLine());

body.push(clause('5', [
  t('Use reasonable efforts to maintain security at the premises and to prevent theft. Unfortunately, experience has shown that some minor theft by customers is inevitable at any public sale. We will, however, take reasonable steps to guard against it — for example, by stationing personnel near small, high-value items — and we will supply an adequate number of staff to work the sale. If we recommend it for a particular sale, we may also hire one or more off-duty police officers to provide security, at a cost to the Seller.'),
], { after: 110 }));
body.push(initialLine());

body.push(clause('6', [
  t('Accept cash, credit cards, and checks as payment at the sale.'),
]));

body.push(clause('7', [
  t('Within fifteen (15) business days after the conclusion of the Estate Sale, High Caliber Estate Sales LLC will distribute the net proceeds of the Estate Sale to the Seller. '),
  b('"Net Proceeds"'),
  t(' shall mean the amount collected by the Liquidator from the sale of the property, less the Liquidator’s commission and any expenses chargeable to the Seller under this Agreement.'),
], { after: 120 }));

body.push(new Paragraph({
  children: [
    t('Our fee for providing the services described above is '),
    b(us(8)),
    b('% '),
    t('of gross sale proceeds, and '),
    b(us(8)),
    b('% '),
    t('of gross proceeds on titled vehicles, tractors, boats, trailers, and similar titled property.'),
  ],
  spacing: { after: 120, line: 240 },
  indent: { left: 360 },
}));

body.push(P([
  t('Our commission is payable on all items we have been told will be included in the sale at the time this Agreement is signed. Because our decision to accept this sale over other estate sale opportunities — and all of our planning and preparation for it — is based on the quantity and quality of the items represented to us, we strongly discourage the removal of items after we have been hired.'),
], { after: 120, indent: { left: 360 } }));

body.push(P([
  b('If ANY items are removed after we have begun working on the sale, we reserve the right to appraise the removed items and to deduct '),
  b(us(8)),
  b('% of the appraised value from the Seller’s share of the proceeds of the sale, although we will always attempt to be fair, reasonable, and understanding in that regard.'),
], { after: 110, indent: { left: 360 } }));
body.push(initialLine());

// ===== PAGE 3 =====
body.push(sectionHeading('THE SELLER SHALL:'));

body.push(clause('1', [
  t('Grant High Caliber Estate Sales LLC and its employees 24/7 access to the premises during all access dates. The premises shall be unoccupied from the access date onward. If access is restricted in any way, or if any persons or animals occupy the home or remain on the premises, the Seller agrees to leave the Liquidator’s setup completely alone and untouched.'),
]));

body.push(clause('2', [
  t('Furnish the Liquidator with keys and security codes to the premises:'),
], { after: 60 }));
body.push(new Table({
  columnWidths: [9720],
  width: { size: 9720, type: WidthType.DXA },
  borders: noBorders,
  indent: { size: 720, type: WidthType.DXA },
  rows: [new TableRow({ children: [lineCell(9720)] })],
}));
body.push(spacer(90));

body.push(clause('3', [
  t('Before the access date of the Estate Sale, remove from the premises — or secure in a locked room or container — all personal items that are '),
  b('not for sale (NFS)'),
  t(', and all other property on the premises that is not to be sold. Any item not removed or secured by a locked method will be considered part of the Estate Sale.'),
]));

body.push(clause('4', [
  t('Waive any claim for loss, theft, or damage against High Caliber Estate Sales LLC (the Liquidator) arising in connection with the Estate Sale.'),
]));

body.push(clause('5', [
  t('Maintain property and casualty insurance covering the premises and the property throughout the term of this Agreement.'),
]));

body.push(clause('6', [
  t('Indemnify, defend, and hold harmless the Liquidator and its members, employees, and contractors from and against any and all claims, actions, damages, liability, and expenses — including attorney fees — in connection with loss of life, personal injury, and/or property damage arising from or in connection with the Estate Sale.'),
]));

body.push(clause('7', [
  t('Not remove '),
  b('any', { underline: { type: UnderlineType.SINGLE } }),
  t(' property from the premises after the date this Agreement is signed, except as set forth in Paragraph 3 above. If any property is removed from the premises after the date of this Agreement, the Liquidator reserves the right to appraise the removed items, and the Seller shall pay the Liquidator a fee equal to '),
  b(us(8)),
  b('% '),
  t('of the price established by the Liquidator for such items, to renegotiate the terms of this Agreement, or to cancel this Agreement.'),
]));

body.push(clause('8', [
  t('Authorize the Liquidator to photograph the property during the Estate Sale and to use those photographs for reference and marketing purposes. The Seller acknowledges that the Liquidator owns all right, title, and interest in all such photographs, and releases the Liquidator from any claim arising out of the use of such images.'),
]));

body.push(clause('9', [
  t('Be responsible for arranging approval of the Estate Sale with any homeowner’s association connected to the premises and for paying any associated fees.'),
], { after: 200 }));

body.push(P([b('Seller agrees to Paragraphs 1–9 above.')], { after: 130 }));
body.push(fieldTable(
  [[{ label: 'Seller Signature:', w: 2400 }, { line: true, w: 4840 }, { label: 'Date:', w: 750 }, { line: true, w: 2450 }]],
  [2400, 4840, 750, 2450],
  { height: 460 }
));

// ===== PAGE 4 =====
body.push(sectionHeading('ADDITIONAL TERMS'));

body.push(p('Seller represents that the Estate has good title to the property, has the power to sell the property without the consent of any other party, and that the property is free and clear of all liens and encumbrances.', { after: 130 }));

body.push(p('Acceptance by the Seller of the net proceeds shall release the Liquidator from any further liability under this Agreement.', { after: 130 }));

body.push(P([
  b('Venue: '),
  t('Venue for the resolution of any dispute through civil litigation shall be in the 37th District Court, City of Warren, Macomb County, Michigan, or in the Macomb County Circuit Court, as jurisdiction allows. This Agreement is governed by the laws of the State of Michigan.'),
], { after: 130 }));

body.push(P([
  b('Cancellation by Seller: '),
  t('Should the Seller cancel this Agreement for any reason, the Seller will pay the Liquidator a cancellation fee of $'),
  b(us(12)),
  t(', and will reimburse the Liquidator for all expenses incurred in connection with the Estate Sale prior to cancellation.'),
], { after: 130 }));

body.push(p('The Liquidator will provide its services on a "best efforts" basis, without warranty of any kind, express or implied. The Liquidator does not guarantee that the Estate Sale will generate any minimum level of revenue.', { after: 130 }));

body.push(p('Services are subject to cancellation if the Seller is found to be in violation of this Agreement, and the Liquidator reserves the right to terminate this Agreement for any reason.', { after: 130 }));

body.push(P([
  b('Weather: '),
  t('When we conduct a sale in Michigan, weather is always a factor, and we will not put anyone at risk during the winter months. If bad weather raises safety concerns, we will postpone and reschedule your sale. Any snow removal or salting required at the premises is at the Seller’s cost.'),
], { after: 130 }));

body.push(P([
  b('Parking: '),
  t('Please specify where parking is allowed on the property.'),
], { after: 70 }));
body.push(fieldTable([[{ line: true, w: CONTENT_W }]], [CONTENT_W], { height: 420 }));
body.push(fieldTable([[{ line: true, w: CONTENT_W }]], [CONTENT_W], { height: 420 }));
body.push(spacer(110));

body.push(P([
  b('Client at Sale: '),
  t('You are, of course, welcome at the house during the setup and pricing process. During the sale days, however, we strongly recommend that the client not be in attendance. A client’s presence at a sale is emotionally difficult, is hard on our team, and deters customers from buying.'),
], { after: 130 }));

body.push(P([
  b('Sale of Property: '),
  t('If the real property has been sold, please coordinate with your realtor. No new homeowner should receive keys until after the Estate Sale has been conducted, and no new homeowner should be present at the sale to measure for carpet, choose paint colors, or similar purposes.'),
], { after: 160 }));

body.push(initialLine());

// ===== SIGNATURE PAGE =====
// The only forced break in the document: it keeps the closing letter and the
// whole signature block together instead of splitting the block across pages.
body.push(P([
  b('Our business is built on referrals. '),
  t('Accordingly, it is important to us that you be happy with our service. Above all, we recognize that in entrusting your sale to us, you are relying on our honesty and integrity. We have always operated, and will always operate, to the highest standards of honesty and integrity.'),
], { after: 130, pageBreakBefore: true }));

body.push(p('If you ever have any questions or concerns in that regard, please let us know. We have found that in almost all cases, potential problems can be avoided if we simply communicate with each other.', { after: 130 }));

body.push(p('In addition, we recognize that every sale is different. We will make every effort to be flexible, to be fair, reasonable, and understanding, and to work within your schedule. We trust that you will do the same.', { after: 130 }));

body.push(p('If this Agreement correctly reflects your understanding of our arrangement, please sign in the space provided below and return one copy to us. We appreciate this opportunity to serve you, and we look forward to a productive sale!', { after: 180 }));

body.push(rule(150));

// Signature block — every rule runs the full width of the page.
const LBL = 2800;
const REST = CONTENT_W - LBL;
const SIG_H = 440; // ~0.3in — room to actually write

// Paired two-per-row where the fields are short, so the block stays on one page.
const HALF = Math.floor(CONTENT_W / 2);

// Both members sign for the Liquidator.
body.push(P([b('LIQUIDATOR:  High Caliber Estate Sales LLC', { size: 22 })], { after: 140 }));

body.push(fieldTable(
  [[
    { label: 'By: William Faitel, Member', w: 2900 }, { line: true, w: HALF - 2900 },
    { label: 'Date:', w: 800 }, { line: true, w: CONTENT_W - HALF - 800 },
  ]],
  [2900, HALF - 2900, 800, CONTENT_W - HALF - 800],
  { height: SIG_H }
));

body.push(fieldTable(
  [[
    { label: 'By: Casey Faitel, Member', w: 2900 }, { line: true, w: HALF - 2900 },
    { label: 'Date:', w: 800 }, { line: true, w: CONTENT_W - HALF - 800 },
  ]],
  [2900, HALF - 2900, 800, CONTENT_W - HALF - 800],
  { height: SIG_H }
));

body.push(P([b('SELLER:', { size: 22 })], { before: 260, after: 140 }));

body.push(fieldTable(
  [[
    { label: 'Seller (signature):', w: 2200 }, { line: true, w: HALF - 2200 },
    { label: 'Date Signed:', w: 1550 }, { line: true, w: CONTENT_W - HALF - 1550 },
  ]],
  [2200, HALF - 2200, 1550, CONTENT_W - HALF - 1550],
  { height: SIG_H }
));

body.push(fieldTable(
  [[
    { label: 'Seller (print name):', w: 2200 }, { line: true, w: HALF - 2200 },
    { label: 'Seller’s Phone:', w: 1750 }, { line: true, w: CONTENT_W - HALF - 1750 },
  ]],
  [2200, HALF - 2200, 1750, CONTENT_W - HALF - 1750],
  { height: SIG_H }
));

body.push(fieldTable(
  [[{ label: 'Email:', w: 950 }, { line: true, w: CONTENT_W - 950 }]],
  [950, CONTENT_W - 950],
  { height: SIG_H }
));

body.push(fieldTable(
  [[{ label: 'Address:', w: 1200 }, { line: true, w: CONTENT_W - 1200 }]],
  [1200, CONTENT_W - 1200],
  { height: SIG_H }
));

body.push(fieldTable(
  [[
    { label: 'City:', w: 750 }, { line: true, w: 4300 },
    { label: 'State:', w: 900 }, { line: true, w: 1400 },
    { label: 'Zip:', w: 640 }, { line: true, w: CONTENT_W - 7990 },
  ]],
  [750, 4300, 900, 1400, 640, CONTENT_W - 7990],
  { height: SIG_H }
));

body.push(fieldTable(
  [[{ label: 'Make check payable to:', w: 2800 }, { line: true, w: CONTENT_W - 2800 }]],
  [2800, CONTENT_W - 2800],
  { height: SIG_H }
));

body.push(spacer(60));
body.push(P([b('Notes:')], { after: 130 }));
body.push(fieldTable(
  [
    [{ line: true, w: CONTENT_W }],
    [{ line: true, w: CONTENT_W }],
    [{ line: true, w: CONTENT_W }],
  ],
  [CONTENT_W],
  { height: SIG_H }
));

// ---------- assemble ----------
const doc = new Document({
  styles: { default: { document: { run: { font: FONT, size: BODY } } } },
  sections: [{
    properties: {
      titlePage: true,
      page: {
        size: { width: 12240, height: 15840, orientation: PageOrientation.PORTRAIT },
        // A logo header is taller than a line of type, so the body starts lower.
        margin: { top: logo ? 1150 : 950, right: 850, bottom: 620, left: 850, header: 340, footer: 270 },
      },
    },
    headers: {
      first: new Header({ children: [] }),
      default: pageHeader(),
    },
    // titlePage gives page 1 its own header AND footer. The first-page header is
    // deliberately empty (the letterhead is in the body), but page 1 still needs
    // the footer — without an explicit `first` footer it would have none.
    footers: {
      first: pageFooter(),
      default: pageFooter(),
    },
    children: body,
  }],
});

Packer.toBuffer(doc).then((buf) => {
  fs.writeFileSync(process.argv[2], buf);
  console.log('wrote ' + process.argv[2]);
});
