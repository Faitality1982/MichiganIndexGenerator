const fs = require('fs');
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType,
  PageOrientation, BorderStyle, PageBreak, UnderlineType,
  Footer, PageNumber,
} = require('docx');

const FONT = 'Calibri';

// ---------- helpers ----------
const t = (text, opts = {}) => new TextRun({ text, font: FONT, size: opts.size || 21, ...opts });

// body paragraph from an array of runs
const P = (children, opts = {}) =>
  new Paragraph({
    children,
    spacing: { after: opts.after === undefined ? 120 : opts.after, line: 252 },
    alignment: opts.alignment,
    indent: opts.indent,
    keepNext: opts.keepNext,
    border: opts.border,
  });

// plain text paragraph
const p = (text, opts = {}) => P([t(text, opts)], opts);

// numbered clause, hanging indent
const clause = (num, runs, opts = {}) =>
  new Paragraph({
    children: [t(num + ') ', { bold: true }), ...runs],
    spacing: { after: opts.after === undefined ? 160 : opts.after, line: 252 },
    indent: { left: 360, hanging: 360 },
  });

// "Initial: ____" line, right-ish
const initialLine = (label) =>
  new Paragraph({
    children: [
      t((label || 'Initial') + ': ', { bold: true }),
      t('___________', { bold: true }),
    ],
    spacing: { after: 200, line: 252 },
    indent: { left: 360 },
  });

const blank = (n) => ' '.repeat(n);
const ul = (text) => t(text, { underline: { type: UnderlineType.SINGLE } });

// checkbox glyph — Segoe UI Symbol renders U+2610 reliably in Word
const checkbox = () => new TextRun({ text: '☐  ', font: 'Segoe UI Symbol', size: 22 });

// fill-in line: "Label: ______________"
const fillIn = (label, len, opts = {}) =>
  new Paragraph({
    children: [t(label + ' ', { bold: opts.bold }), ul(blank(len || 40))],
    spacing: { after: opts.after === undefined ? 160 : opts.after, line: 300 },
    indent: opts.indent,
  });

const sectionHeading = (text) =>
  new Paragraph({
    children: [t(text, { bold: true, size: 24, allCaps: false })],
    spacing: { before: 200, after: 160 },
    keepNext: true,
  });

const rule = () =>
  new Paragraph({
    children: [t('')],
    border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: '000000', space: 1 } },
    spacing: { after: 160 },
  });

const pageBreak = () => new Paragraph({ children: [new PageBreak()] });

// ---------- letterhead ----------
const letterhead = [
  new Paragraph({
    children: [t('HIGH CALIBER ESTATE SALES LLC', { bold: true, size: 40 })],
    alignment: AlignmentType.CENTER,
    spacing: { after: 40 },
  }),
  new Paragraph({
    children: [t('Professional Estate Liquidation — Serving Metro Detroit', { size: 20, italics: true })],
    alignment: AlignmentType.CENTER,
    spacing: { after: 100 },
  }),
  new Paragraph({
    children: [t('32055 Wilson Drive, Warren, MI  [ZIP]', { size: 20 })],
    alignment: AlignmentType.CENTER,
    spacing: { after: 20 },
  }),
  new Paragraph({
    children: [t('Phone: [PHONE]   •   Email: [EMAIL]   •   highcaliberestatesales.com', { size: 20 })],
    alignment: AlignmentType.CENTER,
    spacing: { after: 20 },
  }),
  new Paragraph({
    children: [t('Owner: [OWNER NAME]', { size: 20 })],
    alignment: AlignmentType.CENTER,
    spacing: { after: 160 },
  }),
  rule(),
];

// running header for pages 2+
const runningHead = [
  new Paragraph({
    children: [t('HIGH CALIBER ESTATE SALES LLC', { bold: true, size: 28 })],
    alignment: AlignmentType.CENTER,
    spacing: { after: 40 },
  }),
  rule(),
];

// ---------- document body ----------
const body = [];

// ===== PAGE 1 =====
body.push(...letterhead);

body.push(new Paragraph({
  children: [t('AGREEMENT TO CONDUCT ESTATE SALE', { bold: true, size: 28 })],
  alignment: AlignmentType.CENTER,
  spacing: { after: 240 },
}));

body.push(fillIn('Start Date of Services:', 34));
body.push(fillIn('Date(s) of Sale:', 40));

body.push(p('Thank you for selecting High Caliber Estate Sales LLC to liquidate the contents of the estate known as:', { after: 160 }));

body.push(fillIn('Address:', 60));
body.push(new Paragraph({
  children: [t('City: ', {}), ul(blank(28)), t('   State: ', {}), ul(blank(8)), t('   Zip: ', {}), ul(blank(12))],
  spacing: { after: 200, line: 300 },
}));

body.push(new Paragraph({
  children: [t('The Estate Sale will be held ON SITE.', { bold: true, underline: { type: UnderlineType.SINGLE } })],
  spacing: { after: 200 },
}));

body.push(P([
  t('High Caliber Estate Sales LLC (also referred to in this Agreement as the ', { italics: true, bold: true }),
  t('"Liquidator"', { italics: true, bold: true }),
  t(') shall provide the following services in connection with the sale of the personal property located at the premises of the estate:', { italics: true, bold: true }),
], { after: 200 }));

body.push(sectionHeading('THE LIQUIDATOR SHALL:'));

body.push(clause('1', [
  t('Sort, organize, arrange, and display all items to be sold. If, during that process, we encounter items that appear to be of unusual value or of special sentimental value that you have not told us about, we will consult with you before pricing or selling them. We will use the tables, shelves, cabinets, and similar surfaces available at the premises for display, and we will supply any additional display equipment we consider necessary. The Liquidator will gather and dispose of unsold items that cannot be sold, using ordinary garbage pickup where possible. If the volume or size of the discarded items exceeds ordinary pickup, the Liquidator will arrange for a dumpster and the Seller will pay the dumpster cost.'),
]));
body.push(initialLine());

body.push(P([t('The Liquidator will clean and polish selected items being sold — such as silverware, fine china, furniture, and similar goods — where doing so is necessary to present them well.')], { after: 160 }));

body.push(P([
  t('We do NOT clean the home, windows, floors, walls, carpeting, or similar surfaces after the sale has concluded, and we cannot be held liable for soiled or worn flooring.', { bold: true, underline: { type: UnderlineType.SINGLE } }),
], { after: 120 }));
body.push(initialLine());

body.push(P([
  t('If you would like our staff to wear shoe covers (booties) during the sale, initial here:', { bold: true }),
], { after: 120 }));
body.push(initialLine());

body.push(clause('2', [
  t('Price the property using tags, labels, or signs. During the course of the Estate Sale the Liquidator shall have full authority to negotiate prices with customers.'),
]));

body.push(P([t('The number of days your sale runs determines the discount schedule:', { bold: true })], { after: 120 }));

const dayLine = (label, text) => new Paragraph({
  children: [checkbox(), t(label, { bold: true }), t(text)],
  spacing: { after: 80, line: 252 },
  indent: { left: 720, hanging: 360 },
});

body.push(dayLine('One-day sale: ', 'Full price / half way through the sale day, 25% off.'));
body.push(dayLine('Two-day sale: ', 'Day One = full price / Day Two = 50% off and a $5 bag.'));
body.push(dayLine('Three-day sale: ', 'Day One = full price / Day Two = 25% off / Day Three = 50% off and a $5 bag.'));
body.push(dayLine('Four-day sale: ', 'Day One = full price / Day Two = 25% off / Day Three = 50% off / Day Four = 75% off and a $5 bag.'));

body.push(new Paragraph({
  children: [checkbox(), t('Custom discount schedule: ', { bold: true })],
  spacing: { after: 100, line: 252 },
  indent: { left: 720, hanging: 360 },
}));
body.push(new Paragraph({
  children: [
    t('Day One: '), ul(blank(14)), t('   Day Two: '), ul(blank(14)),
    t('   Day Three: '), ul(blank(14)), t('   Day Four: '), ul(blank(14)),
  ],
  spacing: { after: 160, line: 300 },
  indent: { left: 720 },
}));
body.push(initialLine());

// ===== PAGE 2 =====
body.push(pageBreak());
body.push(...runningHead);

body.push(clause('3', [
  t('The Seller shall '),
  t('NOT', { bold: true, underline: { type: UnderlineType.SINGLE } }),
  t(' change the price of any item. The Liquidator reserves the right to remove items from the premises for research, appraisal, or safekeeping, and to lock up small or high-value items. Any such item will be priced in the best interest of the Seller.'),
]));
body.push(initialLine());

body.push(clause('4', [
  t('Advertise the Estate Sale at the Liquidator’s expense through EstateSales.net, Facebook, Instagram, neighborhood apps, and selected local newspapers. The Liquidator will also place signs in the yard during the sale and additional directional signs in the vicinity of the sale where permitted by local ordinance.'),
]));
body.push(initialLine());

body.push(clause('5', [
  t('Use reasonable efforts to maintain security at the premises and to prevent theft. Unfortunately, experience has shown that some minor theft by customers is inevitable at any public sale. We will, however, take reasonable steps to guard against it — for example, by stationing personnel near small, high-value items — and we will supply an adequate number of staff to work the sale. If we recommend it for a particular sale, we may also hire one or more off-duty police officers to provide security, at a cost to the Seller.'),
]));
body.push(initialLine());

body.push(clause('6', [
  t('Accept cash, credit cards, and checks as payment at the sale.'),
]));

body.push(clause('7', [
  t('Within fifteen (15) business days after the conclusion of the Estate Sale, High Caliber Estate Sales LLC will distribute the net proceeds of the Estate Sale to the Seller. '),
  t('"Net Proceeds"', { bold: true }),
  t(' shall mean the amount collected by the Liquidator from the sale of the property, less the Liquidator’s commission and any expenses chargeable to the Seller under this Agreement.'),
]));

body.push(new Paragraph({
  children: [
    t('Our fee for providing the services described above is '),
    ul(blank(8)),
    t('% of gross sale proceeds, and '),
    ul(blank(8)),
    t('% of gross proceeds on titled vehicles, tractors, boats, trailers, and similar titled property.'),
  ],
  spacing: { after: 160, line: 300 },
  indent: { left: 360 },
}));

body.push(P([
  t('Our commission is payable on all items we have been told will be included in the sale at the time this Agreement is signed. Because our decision to accept this sale over other estate sale opportunities — and all of our planning and preparation for it — is based on the quantity and quality of the items represented to us, we strongly discourage the removal of items after we have been hired.'),
], { after: 160, indent: { left: 360 } }));

body.push(P([
  t('If ANY items are removed after we have begun working on the sale, we reserve the right to appraise the removed items and to deduct ', { bold: true }),
  t('_______%', { bold: true, underline: { type: UnderlineType.SINGLE } }),
  t(' of the appraised value from the Seller’s share of the proceeds of the sale, although we will always attempt to be fair, reasonable, and understanding in that regard.', { bold: true }),
], { after: 120, indent: { left: 360 } }));
body.push(initialLine());

// ===== PAGE 3 =====
body.push(pageBreak());
body.push(...runningHead);

body.push(sectionHeading('THE SELLER SHALL:'));

body.push(clause('1', [
  t('Grant High Caliber Estate Sales LLC and its employees 24/7 access to the premises during all access dates. The premises shall be unoccupied from the access date onward. If access is restricted in any way, or if any persons or animals occupy the home or remain on the premises, the Seller agrees to leave the Liquidator’s setup completely alone and untouched.'),
]));

body.push(new Paragraph({
  children: [t('2) ', { bold: true }), t('Furnish the Liquidator with keys and security codes to the premises: '), ul(blank(24))],
  spacing: { after: 160, line: 300 },
  indent: { left: 360, hanging: 360 },
}));

body.push(clause('3', [
  t('Before the access date of the Estate Sale, remove from the premises — or secure in a locked room or container — all personal items that are '),
  t('not for sale (NFS)', { bold: true }),
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
  t('any', { bold: true, underline: { type: UnderlineType.SINGLE } }),
  t(' property from the premises after the date this Agreement is signed, except as set forth in Paragraph 3 above. If any property is removed from the premises after the date of this Agreement, the Liquidator reserves the right to appraise the removed items, and the Seller shall pay the Liquidator a fee equal to '),
  t('_______%', { bold: true, underline: { type: UnderlineType.SINGLE } }),
  t(' of the price established by the Liquidator for such items, to renegotiate the terms of this Agreement, or to cancel this Agreement.'),
]));

body.push(clause('8', [
  t('Authorize the Liquidator to photograph the property during the Estate Sale and to use those photographs for reference and marketing purposes. The Seller acknowledges that the Liquidator owns all right, title, and interest in all such photographs, and releases the Liquidator from any claim arising out of the use of such images.'),
]));

body.push(clause('9', [
  t('Be responsible for arranging approval of the Estate Sale with any homeowner’s association connected to the premises and for paying any associated fees.'),
]));

body.push(new Paragraph({
  children: [t('Seller agrees to Paragraphs 1–9 above.   Signature: ', { bold: true }), ul(blank(40))],
  spacing: { before: 240, after: 200, line: 300 },
}));

// ===== PAGE 4 =====
body.push(pageBreak());
body.push(...runningHead);

body.push(sectionHeading('ADDITIONAL TERMS'));

const term = (label, text) => new Paragraph({
  children: [t(label, { bold: true }), t(text)],
  spacing: { after: 160, line: 252 },
});

body.push(p('Seller represents that the Estate has good title to the property, has the power to sell the property without the consent of any other party, and that the property is free and clear of all liens and encumbrances.', { after: 160 }));

body.push(p('Acceptance by the Seller of the net proceeds shall release the Liquidator from any further liability under this Agreement.', { after: 160 }));

body.push(P([
  t('Venue: ', { bold: true }),
  t('Venue for the resolution of any dispute through civil litigation shall be in the 37th District Court, City of Warren, Macomb County, Michigan, or in the Macomb County Circuit Court, as jurisdiction allows. This Agreement is governed by the laws of the State of Michigan.'),
], { after: 160 }));

body.push(P([
  t('Cancellation by Seller: ', { bold: true }),
  t('Should the Seller cancel this Agreement for any reason, the Seller will pay the Liquidator a cancellation fee of $'),
  ul(blank(10)),
  t(', and will reimburse the Liquidator for all expenses incurred in connection with the Estate Sale prior to cancellation.'),
], { after: 160 }));

body.push(p('The Liquidator will provide its services on a "best efforts" basis, without warranty of any kind, express or implied. The Liquidator does not guarantee that the Estate Sale will generate any minimum level of revenue.', { after: 160 }));

body.push(p('Services are subject to cancellation if the Seller is found to be in violation of this Agreement, and the Liquidator reserves the right to terminate this Agreement for any reason.', { after: 160 }));

body.push(P([
  t('Weather: ', { bold: true }),
  t('When we conduct a sale in Michigan, weather is always a factor, and we will not put anyone at risk during the winter months. If bad weather raises safety concerns, we will postpone and reschedule your sale. Any snow removal or salting required at the premises is at the Seller’s cost.'),
], { after: 160 }));

body.push(new Paragraph({
  children: [t('Parking: ', { bold: true }), t('Please specify where parking is allowed on the property. '), ul(blank(30))],
  spacing: { after: 100, line: 300 },
}));
body.push(new Paragraph({ children: [ul(blank(85))], spacing: { after: 160, line: 300 } }));

body.push(P([
  t('Client at Sale: ', { bold: true }),
  t('You are, of course, welcome at the house during the setup and pricing process. During the sale days, however, we strongly recommend that the client not be in attendance. A client’s presence at a sale is emotionally difficult, is hard on our team, and deters customers from buying.'),
], { after: 160 }));

body.push(P([
  t('Sale of Property: ', { bold: true }),
  t('If the real property has been sold, please coordinate with your realtor. No new homeowner should receive keys until after the Estate Sale has been conducted, and no new homeowner should be present at the sale to measure for carpet, choose paint colors, or similar purposes.'),
], { after: 200 }));

body.push(initialLine());

// ===== PAGE 5 =====
body.push(pageBreak());
body.push(...runningHead);

body.push(P([
  t('Our business is built on referrals. ', { bold: true }),
  t('Accordingly, it is important to us that you be happy with our service. Above all, we recognize that in entrusting your sale to us, you are relying on our honesty and integrity. We have always operated, and will always operate, to the highest standards of honesty and integrity.'),
], { after: 160 }));

body.push(p('If you ever have any questions or concerns in that regard, please let us know. We have found that in almost all cases, potential problems can be avoided if we simply communicate with each other.', { after: 160 }));

body.push(p('In addition, we recognize that every sale is different. We will make every effort to be flexible, to be fair, reasonable, and understanding, and to work within your schedule. We trust that you will do the same.', { after: 160 }));

body.push(p('If this Agreement correctly reflects your understanding of our arrangement, please sign in the space provided below and return one copy to us. We appreciate this opportunity to serve you, and we look forward to a productive sale!', { after: 240 }));

body.push(rule());

body.push(new Paragraph({
  children: [t('Liquidator:  High Caliber Estate Sales LLC', { bold: true, size: 22 })],
  spacing: { after: 240 },
}));

const sigLine = (label, len) => new Paragraph({
  children: [t(label + ' ', { bold: true }), ul(blank(len))],
  spacing: { after: 200, line: 320 },
});

body.push(sigLine('Seller (signature):', 46));
body.push(sigLine('Seller (print name):', 46));
body.push(sigLine('Date Signed:', 30));
body.push(sigLine('Seller’s Phone:', 30));
body.push(sigLine('Email:', 50));
body.push(sigLine('Address:', 52));
body.push(new Paragraph({
  children: [t('City: ', { bold: true }), ul(blank(26)), t('  State: ', { bold: true }), ul(blank(8)), t('  Zip: ', { bold: true }), ul(blank(12))],
  spacing: { after: 200, line: 320 },
}));
body.push(sigLine('Make check payable to:', 40));

body.push(new Paragraph({
  children: [t('Notes:', { bold: true })],
  spacing: { after: 140, line: 320 },
}));
for (let i = 0; i < 4; i++) {
  body.push(new Paragraph({ children: [ul(blank(88))], spacing: { after: 160, line: 320 } }));
}

// ---------- assemble ----------
const doc = new Document({
  styles: { default: { document: { run: { font: FONT, size: 21 } } } },
  sections: [{
    properties: {
      page: {
        size: { width: 12240, height: 15840, orientation: PageOrientation.PORTRAIT },
        margin: { top: 720, right: 900, bottom: 720, left: 900 },
      },
    },
    footers: {
      default: new Footer({
        children: [
          new Paragraph({
            alignment: AlignmentType.CENTER,
            spacing: { before: 120 },
            children: [
              t('High Caliber Estate Sales LLC — Agreement to Conduct Estate Sale     Seller Initials: ______     Page ', { size: 16 }),
              new TextRun({ children: [PageNumber.CURRENT], font: FONT, size: 16 }),
              t(' of ', { size: 16 }),
              new TextRun({ children: [PageNumber.TOTAL_PAGES], font: FONT, size: 16 }),
            ],
          }),
        ],
      }),
    },
    children: body,
  }],
});

Packer.toBuffer(doc).then((buf) => {
  fs.writeFileSync(process.argv[2], buf);
  console.log('wrote ' + process.argv[2]);
});
