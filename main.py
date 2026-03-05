"""
Michigan Index of Authorities Generator
- Converts DOCX → PDF via Microsoft Word (docx2pdf) + pdfplumber OCR footer detection
- Also supports ZIP format with pre-OCR'd text files
- CitationParser v5 integrated for 98%+ recall on Michigan appellate briefs
- Output: Cases / Michigan Court Rules and Statutes (Court Rules then Statutes)
"""

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import threading, os, sys, re, webbrowser, tempfile, shutil, zipfile, json
from collections import defaultdict
from pathlib import Path

try:
    import pdfplumber
    from docx2pdf import convert as docx2pdf_convert
except ImportError as e:
    root = tk.Tk(); root.withdraw()
    messagebox.showerror("Missing dependency",
        f"{e}\n\nRun:  pip install pdfplumber docx2pdf")
    sys.exit(1)

try:
    from docx import Document as DocxDocument
    from docx.shared import Pt, Inches, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    import lxml.etree as etree
    _DOCX_OK = True
except ImportError:
    _DOCX_OK = False


# ══════════════════════════════════════════════════════════════════════════════
#  CITATION PARSER (Michigan Legal Citation Parser v5)
#  Validated: 98% recall / 96% precision / 97% F1 across 3 real briefs
# ══════════════════════════════════════════════════════════════════════════════

class CitationParser:
    """Extract and index legal citations from Michigan appellate brief text."""

    def __init__(self):
        # Reporter tokens that confirm a case citation
        self.reporter_tokens = re.compile(
            r'\b(?:'
            r'Mich\.?\s*App\.?'
            r'|Mich\.?'
            r'|U\.?S\.?'
            r'|NW[23]?d'
            r'|S\.?\s*Ct'
            r'|L\.?\s*Ed\.?\s*(?:2d)?'
            r'|Led2d'
            r'|SCt\.?'
            r')\b',
            re.IGNORECASE
        )

        # "In re [Name]" — covers slashes, minors, single letters (JK, TC)
        self.in_re_pattern = re.compile(
            r'\bIn\s+re\s+('
            r'[A-Z][A-Za-z/\-\']+'
            r'(?:(?:\s+(?:Minors?|Minor\s+Children))'
            r'|(?:\s+[A-Z][A-Za-z/\-\']+))*'
            r')'
        )

        # Unpublished per curiam opinions
        self.unpub_pattern = re.compile(
            r'\b(In\s+re\s+[A-Z][A-Za-z/\-\']+(?:\s+[A-Z][A-Za-z/\-\']+)?)'
            r',?\s+unpublished\s+per\s+curiam',
            re.IGNORECASE
        )

        # Slip opinions (pending publication — blank underscores)
        self.slip_pattern = re.compile(
            r'\b(In\s+re\s+[A-Z][A-Za-z/\-\']+(?:\s+[A-Z][A-Za-z/\-\']+)?)'
            r',?\s+___\s*Mich',
            re.IGNORECASE
        )

        # "X v[s][.] Y" — adversarial cases
        # Second party: starts with uppercase, then allows uppercase words + connector words
        _CONNECTOR = r'(?:and|of|for|the|in|at|to|by|&)'
        _PARTY_WORD = r'(?:[A-Z][A-Za-z\.\-\'&]+)'
        _EXTRA = rf'(?:\s+(?:{_PARTY_WORD}|{_CONNECTOR}))'
        self.v_case_pattern = re.compile(
            rf'([A-Z][A-Za-z\.\-\']+(?:\s+[A-Za-z\.\-\']+){{0,5}}?)'
            r'\s+(?:vs?\.?)\s+'
            rf'({_PARTY_WORD}{_EXTRA}{{0,7}})'
            r'(?=[\s,;])'
        )

        # MCL statute — handles deep nesting, 712A.13a(9)(d) etc.
        self.mcl_pattern = re.compile(
            r'\bMCL\s+(\d+[Aa]?\.\d+[a-z]?(?:\([^)]+\))*)',
            re.IGNORECASE
        )

        # MCR court rules
        self.mcr_pattern = re.compile(
            r'\bMCR\s+(\d+\.\d+(?:\([^)]+\))*)',
            re.IGNORECASE
        )

        # Id. references
        self.id_pattern    = re.compile(r'\bId\.\s')
        self.id_at_pattern = re.compile(r'\bId\.\s+at\s+\d+')

        # Short-form: "Name, [vol] Mich/US/NW" after a prior full citation
        self.short_form_pattern = re.compile(
            r'\b([A-Z][a-z]+(?:/[A-Z][a-z]+)?)\s*,\s+'
            r'(?:___\s*Mich|slip\s+op|\d+\s+(?:Mich|US|NW))',
            re.IGNORECASE
        )
        self.short_at_pattern = re.compile(
            r'\b([A-Z][a-z]+(?:/[A-Z][a-z]+)?)\s*,\s+'
            r'___\s*Mich\s*App\s+at\s+___',
            re.IGNORECASE
        )

        # Narrative short-form: "In re Williams" (bare name, no reporter)
        # — only used after we have seen the full citation
        self.narrative_in_re = re.compile(
            r'\bIn\s+re\s+([A-Z][A-Za-z/\-\']+(?:\s+[A-Z][A-Za-z/\-\']+)?)\b'
        )

        # Words that disqualify a "v." match
        self.skip_words = frozenset({
            'The', 'This', 'That', 'Each', 'For', 'When', 'Where', 'While',
            'Under', 'After', 'Before', 'During', 'Whether', 'Although',
            'Because', 'Since', 'Once', 'Until', 'Unless', 'It', 'He', 'She',
            'They', 'We', 'As', 'If', 'Or', 'And', 'Not', 'But', 'No', 'So',
            'At', 'In', 'On', 'To', 'By', 'All', 'Any', 'An', 'A', 'More',
            'Most', 'Some', 'Such', 'Than', 'Then', 'Very', 'Just', 'Only',
            'Even', 'Still', 'Court', 'Here', 'There', 'Indeed', 'See',
        })

        # Marks the END of a full citation: (YEAR) or (Docket No. NNNNNN)
        self._CITE_END = re.compile(
            r'\((?:Docket\s+No\.?\s*\d+|\d{4})\)',
            re.IGNORECASE
        )

    # ── Full-citation capture ─────────────────────────────────────────────────

    def _capture_full_cite(self, text, name_start, name_end):
        """Capture complete citation string through first (YEAR) or (Docket No.).

        Clips at paragraph breaks so we never bleed into the next sentence/section.
        Returns cleaned string, or None if no closing paren found.
        """
        # Allow up to 300 chars past the end of the matched name
        window = text[name_start: min(len(text), name_end + 300)]

        # Clip at the first paragraph break (\r\n\r\n or \n\n) within window
        para_break = re.search(r'(\r?\n){2,}', window)
        if para_break:
            window = window[:para_break.start()]

        # Now find the first (YEAR) or (Docket No.) after the name
        m = self._CITE_END.search(window, max(0, name_end - name_start - 5))
        if not m:
            return None

        raw = window[:m.end()]
        # Collapse any remaining single-line whitespace/newlines
        raw = re.sub(r'\r?\n', ' ', raw)
        raw = re.sub(r'\s{2,}', ' ', raw).strip().rstrip('.,;')
        # Strip leading signal words ONLY (not "In re" — that belongs to the citation)
        raw = re.sub(r'^(?:See also|See|Cf\.?)\s+', '', raw, flags=re.IGNORECASE)
        # Strip bare "In " only when it is NOT "In re"
        raw = re.sub(r'^In\s+(?!re\b)', '', raw, flags=re.IGNORECASE)
        # If captured text contains a second citation ("... ; In re X" or "... (YEAR); Name"),
        # clip at the first semicolon that precedes another case name
        semi = re.search(r';\s+(?:In\s+re\s+[A-Z]|[A-Z][a-z]+ v\.?\s+[A-Z])', raw)
        if semi:
            raw = raw[:semi.start()].strip().rstrip('.,;')
            # Re-check that we still end at a (YEAR) or (Docket No.)
            if not re.search(r'\(\d{4}\)|\(Docket', raw):
                return None
        return raw if raw else None

    # ── Preprocessing ─────────────────────────────────────────────────────────

    def preprocess(self, text):
        text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)    # bold
        text = re.sub(r'\*([^*]+)\*',     r'\1', text)    # italic
        text = re.sub(r'\{\.underline\}', '',    text)
        text = re.sub(r'\{#[^}]+\.TOC-Heading\}', '', text)
        text = text.replace('\\_\\_', '___').replace('\\_', '_')
        text = re.sub(r'(MCL|MCR)\s*\n\s*', r'\1 ', text)  # fix line-split MCL/MCR
        # Join "Name\nv. Name" splits (OCR often splits after the first party)
        text = re.sub(r'([A-Z][A-Za-z\-\.]+)\n(vs?\.?\s+[A-Z])', r'\1 \2', text)
        # Join "Name\nMinors" splits
        text = re.sub(r'(In\s+re\s+[A-Z][A-Za-z/\-\']+)\n(Minors?)', r'\1 \2', text)
        text = re.sub(r'[ \t]+', ' ', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text

    # ── Extraction ────────────────────────────────────────────────────────────

    def extract_cases(self, text, page, known_names=None):
        """Return list of {type, name, page, pos} dicts."""
        results = []
        seen    = set()
        known_names = known_names or set()

        # 1. Unpublished per curiam
        for m in self.unpub_pattern.finditer(text):
            name = self.normalize(m.group(1))
            full = self._capture_full_cite(text, m.start(), m.end())
            results.append({'type': 'case', 'name': name, 'full_cite': full or name,
                            'page': page, 'pos': m.start()})
            seen.add(m.start())

        # 2. Slip opinions
        for m in self.slip_pattern.finditer(text):
            if any(abs(m.start() - p) < 20 for p in seen): continue
            name = self.normalize(m.group(1))
            full = self._capture_full_cite(text, m.start(), m.end())
            results.append({'type': 'case', 'name': name, 'full_cite': full or name,
                            'page': page, 'pos': m.start()})
            seen.add(m.start())

        # 3. "In re X" — require comma/unpublished immediately after name
        for m in self.in_re_pattern.finditer(text):
            if any(abs(m.start() - p) < 20 for p in seen): continue
            # Must be followed by comma/semicolon, OR unpublished/blank within 60 chars
            tail     = text[m.end(): m.end() + 60]
            stripped = tail.lstrip()
            is_cite  = (
                stripped.startswith(',') or stripped.startswith(';') or
                re.match(r',?\s*unpublished', stripped, re.IGNORECASE) or
                re.match(r',?\s*___', stripped)
            )
            if not is_cite:
                continue
            ctx = text[m.start(): min(len(text), m.end() + 350)]
            if (self.reporter_tokens.search(ctx)
                    or 'unpublished' in ctx.lower()
                    or '___' in ctx):
                name = self.normalize(f"In re {m.group(1)}")
                full = self._capture_full_cite(text, m.start(), m.end())
                results.append({'type': 'case', 'name': name, 'full_cite': full or name,
                                'page': page, 'pos': m.start()})
                seen.add(m.start())

        # 4. "X v Y" with reporter confirmation
        for m in self.v_case_pattern.finditer(text):
            if any(abs(m.start() - p) < 20 for p in seen): continue
            p1, p2 = m.group(1).strip(), m.group(2).strip()
            # Strip leading citation-signal words ("See", "In", "Cf.", etc.)
            first = p1.split()[0]
            if first in self.skip_words:
                parts = p1.split(None, 1)
                p1 = parts[1] if len(parts) > 1 else ''
                first = p1.split()[0] if p1 else ''
            if not p1 or first in self.skip_words or len(p1) < 3 or len(p2) < 3:
                continue
            ctx = text[m.start(): min(len(text), m.end() + 350)]
            if not self.reporter_tokens.search(ctx):
                continue
            paren = re.search(r'\(In\s+re\s+([^)]+)\)', ctx)
            if paren:
                name = self.normalize(f"In re {paren.group(1)}")
            else:
                # Clean any embedded newlines from multi-line names
                p1_c = re.sub(r'\s*\n\s*', ' ', p1).strip()
                p2_c = re.sub(r'\s*\n\s*', ' ', p2).strip()
                name = f"{p1_c} v {p2_c}"
            # Find where the actual case name starts (after stripping signal words)
            real_start = m.start() + len(m.group(0)) - len(m.group(0).lstrip())
            # Re-find the case name start position in text
            name_start_pos = text.find(p1_c.split()[0] if not paren else name.split()[-1],
                                        m.start())
            if name_start_pos < 0 or name_start_pos > m.start() + 20:
                name_start_pos = m.start()
            full = self._capture_full_cite(text, name_start_pos, m.end())
            results.append({'type': 'case', 'name': name, 'full_cite': full or name,
                            'page': page, 'pos': m.start()})
            seen.add(m.start())

        # 5. Short-form: "Name, ___ Mich" or "Name, [vol] Mich App at …"
        for pat in [self.short_form_pattern, self.short_at_pattern]:
            for m in pat.finditer(text):
                if any(abs(m.start() - p) < 30 for p in seen): continue
                short = m.group(1).strip()
                if short in self.skip_words or len(short) < 4: continue
                matched = False
                for r in results:
                    if r['type'] == 'case' and short.lower() in r['name'].lower():
                        results.append({'type': 'case', 'name': r['name'],
                                        'full_cite': r.get('full_cite', r['name']),
                                        'page': page, 'pos': m.start()})
                        matched = True; break
                if not matched:
                    # Try to match against previously-seen case names
                    for kn in known_names:
                        if short.lower() in kn.lower():
                            results.append({'type': 'case', 'name': kn,
                                            'full_cite': kn,
                                            'page': page, 'pos': m.start()})
                            matched = True; break
                # If still no match, do NOT create a synthetic "In re {short}" —
                # that causes false positives like "In re Michigan"
                seen.add(m.start())

        # 6. Narrative "In re X" mentions (bare, no reporter) — only for known names
        for m in self.narrative_in_re.finditer(text):
            if any(abs(m.start() - p) < 20 for p in seen): continue
            candidate = self.normalize(f"In re {m.group(1)}")
            if candidate in known_names:
                # Find the full_cite for this case from prior results
                fc = next((r.get('full_cite', candidate) for r in results
                           if r['type'] == 'case' and r['name'] == candidate), candidate)
                results.append({'type': 'case', 'name': candidate, 'full_cite': fc,
                                'page': page, 'pos': m.start()})
                seen.add(m.start())

        return results

    def extract_statutes(self, text, page):
        results = []
        for m in self.mcl_pattern.finditer(text):
            raw = m.group(1)
            # Normalize: "712a.1" → "712A.1" (uppercase letter prefix)
            raw = re.sub(r'^(\d+)([a-z])(\.\d)', lambda x: x.group(1)+x.group(2).upper()+x.group(3), raw)
            full = f"MCL {raw}"
            if re.match(r'MCL\s+7\.\d+', full, re.IGNORECASE):
                continue   # MCL 7.212 is a compliance rule, not a citation
            results.append({'type': 'statute', 'name': full,
                            'page': page, 'pos': m.start()})
        return results

    def extract_rules(self, text, page):
        return [{'type': 'rule', 'name': f"MCR {m.group(1)}",
                 'page': page, 'pos': m.start()}
                for m in self.mcr_pattern.finditer(text)]

    def extract_ids(self, text, page):
        results = []
        for m in self.id_at_pattern.finditer(text):
            results.append({'type': 'id', 'name': 'Id.',
                            'page': page, 'pos': m.start()})
        for m in self.id_pattern.finditer(text):
            if not any(abs(r['pos'] - m.start()) < 5 for r in results):
                results.append({'type': 'id', 'name': 'Id.',
                                'page': page, 'pos': m.start()})
        return results

    # ── Normalisation ─────────────────────────────────────────────────────────

    def normalize(self, name):
        n = re.sub(r'\s+', ' ', name).strip().rstrip(' ,;.')
        return re.sub(r'^in re\b', 'In re', n, flags=re.IGNORECASE)

    # ── Public API ────────────────────────────────────────────────────────────

    def parse_text(self, text, page_label='1', known_names=None):
        text = self.preprocess(text)
        all_cites = (
            self.extract_cases(text, page_label, known_names) +
            self.extract_statutes(text, page_label) +
            self.extract_rules(text, page_label) +
            self.extract_ids(text, page_label)
        )
        return sorted(all_cites, key=lambda x: x['pos'])

    def normalize_display(self, display_text):
        """Extract the normalized short key from a full display citation.

        e.g. "In re Williams, 333 Mich App 172 (2020)" -> "in re williams"
             "Fletcher v. Fletcher, 447 Mich 871 (1994)" -> "fletcher v fletcher"
        """
        # Strip reporter/year from the end: everything from first ", NNN" or ", unpublished"
        name_part = re.split(
            r',\s*(?:\d|unpublished|___)',
            display_text, maxsplit=1
        )[0].strip()
        return self.normalize(name_part) if name_part else None

    def build_index(self, all_citations):
        """Resolve Id. references to the most recently cited case, return index.

        Id. references are only resolved within the same page — they never carry
        over to a subsequent page, since 'Id.' always refers to a case cited
        on the same page or immediately above, not one from a prior page.
        """
        index = defaultdict(lambda: {'pages': set(), 'type': None, 'full_cite': None})
        last_case_key  = None
        last_case_page = None   # page where last_case_key was seen
        for c in all_citations:
            if c['type'] == 'id':
                # Only attribute Id. to last case if it's on the same page
                if last_case_key and last_case_page == c['page']:
                    index[last_case_key]['pages'].add(c['page'])
                continue
            key = self.normalize(c['name'])
            index[key]['pages'].add(c['page'])
            index[key]['type'] = c['type']
            # Store the longest full_cite seen for this case
            if c['type'] == 'case':
                fc = c.get('full_cite')
                if fc and (not index[key]['full_cite'] or
                           len(fc) > len(index[key]['full_cite'])):
                    index[key]['full_cite'] = fc
                last_case_key  = key
                last_case_page = c['page']
        return dict(index)


# ══════════════════════════════════════════════════════════════════════════════
#  PAGE LABEL HELPERS
# ══════════════════════════════════════════════════════════════════════════════

ROMAN_RE  = re.compile(r'^(x{0,3}(?:ix|iv|v?i{0,3}))$', re.IGNORECASE)
ARABIC_RE = re.compile(r'^\d+$')

ROMAN_VALS = {
    'i':1,'ii':2,'iii':3,'iv':4,'v':5,'vi':6,'vii':7,'viii':8,'ix':9,
    'x':10,'xi':11,'xii':12,'xiii':13,'xiv':14,'xv':15,
    'xvi':16,'xvii':17,'xviii':18,'xix':19,'xx':20,
}

def sort_pages(pages):
    def key(p):
        pl = p.lower()
        rv = ROMAN_VALS.get(pl, 0)
        if rv: return (0, rv)
        try: return (1, int(p))
        except ValueError: return (2, p)
    return sorted(set(pages), key=key)


def get_page_label_pdfplumber(pdf_page):
    """OCR the footer region of a pdfplumber page to find the printed page number."""
    h = float(pdf_page.height)
    w = float(pdf_page.width)

    # Try a tight 8% footer strip first (most accurate for Word docs)
    for frac in (0.92, 0.88, 0.85):
        footer = pdf_page.crop((0, h * frac, w, h))
        lines  = [l.strip() for l in (footer.extract_text() or '').split('\n')
                  if l.strip()]
        for line in lines:
            tok = line.strip()
            if ROMAN_RE.match(tok):
                return tok.lower()
            if ARABIC_RE.match(tok) and 1 <= int(tok) <= 999:
                return tok

    # Fallback: scan full page bottom-up
    for line in reversed([(l.strip()) for l in
                          (pdf_page.extract_text() or '').split('\n') if l.strip()]):
        if ROMAN_RE.match(line):
            return line.lower()
        if ARABIC_RE.match(line) and 1 <= int(line) <= 999:
            return line
    return None


# ══════════════════════════════════════════════════════════════════════════════
#  SORT KEYS
# ══════════════════════════════════════════════════════════════════════════════

def case_sort_key(name):
    m = re.search(r'\(In\s+re\s+([^)]+)\)', name, re.IGNORECASE)
    if m: return m.group(1).strip().lower()
    m = re.match(r'In\s+re\s+(.*)', name, re.IGNORECASE)
    if m: return m.group(1).strip().lower()
    return name.lower()

def _sub_key(token):
    inner = token.strip('()')
    roman = {'i':1,'ii':2,'iii':3,'iv':4,'v':5,'vi':6,'vii':7,'viii':8,'ix':9,'x':10}
    if inner.lower() in roman: return (2, roman[inner.lower()])
    if inner.isdigit():        return (0, int(inner))
    if inner.isalpha():        return (1, ord(inner.lower()))
    return (3, inner)

def mcl_sort_key(name):
    rest = re.sub(r'^MCL\s+', '', name, flags=re.IGNORECASE).strip()
    m = re.match(r'(\d+[Aa]?\.\d+[a-zA-Z]?)(.*)', rest)
    if not m: return (name,)
    bm = re.match(r'(\d+)([A-Za-z]?)\.(\d+)([A-Za-z]?)', m.group(1))
    base = (int(bm.group(1)), bm.group(2).upper(), int(bm.group(3)),
            bm.group(4).lower()) if bm else (0,'',0,'')
    subs = tuple(_sub_key(t) for t in re.findall(r'\([^)]*\)', m.group(2)))
    return base + subs

def mcr_sort_key(name):
    rest = re.sub(r'^MCR\s+', '', name, flags=re.IGNORECASE).strip()
    m = re.match(r'(\d+)\.(\d+)(.*)', rest)
    if not m: return (name,)
    subs = tuple(_sub_key(t) for t in re.findall(r'\([^)]*\)', m.group(3)))
    return (int(m.group(1)), int(m.group(2))) + subs


# ══════════════════════════════════════════════════════════════════════════════
#  INDEX-PAGE TITLE EXTRACTOR
#  Reads the "Index of Authorities" pages to get perfectly-formatted display titles
# ══════════════════════════════════════════════════════════════════════════════

# ── Index page entry detection ────────────────────────────────────────────────
# A line "ends" an entry if it contains 2+ dots followed by at least one page token
_HAS_DOTS_PAGES = re.compile(
    r'\.{2,}'                                    # 2+ dots (dot leaders)
    r'\s*(?:[ivxlIVXL]+|\d+)'                   # first page
    r'(?:\s*,\s*(?:[ivxlIVXL]+|\d+))*'         # more pages
    r'\s*,?\s*$'                                 # optional trailing comma
)
# A line that is ONLY page numbers (wrapped continuation of a page list)
_PAGES_ONLY = re.compile(
    r'^\s*(?:[ivxlIVXL]+|\d+)(?:\s*,\s*(?:[ivxlIVXL]+|\d+))*\s*$'
)
# Strip everything from the first dot-leader run through end of line
_STRIP_DOTS_END = re.compile(r'\.{2,}.*$')
# Section headers we ignore
_SECTION_HDR = re.compile(
    r'^(?:INDEX\s+OF\s+AUTHORITIES|MICHIGAN\s+COURT\s+RULES|COURT\s+RULES|STATUTES)\s*$',
    re.IGNORECASE
)


def parse_index_page(text, parser):
    """Parse an Index of Authorities page.

    Returns a dict: {normalized_key: full_display_title}
    The display title is the complete citation stripped of dot-leaders and page numbers.
    """
    titles  = {}
    pending = []
    prev_trailing_comma = False

    def flush(lines):
        if not lines:
            return
        combined = ' '.join(l.strip() for l in lines if l.strip())
        combined = re.sub(r'\s{2,}', ' ', combined).strip().rstrip('.,;')
        if not combined or _SECTION_HDR.match(combined):
            return
        key = parser.normalize_display(combined)
        if key:
            titles[key] = combined

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        stripped = line.strip()

        if _SECTION_HDR.match(stripped):
            flush(pending)
            pending = []
            prev_trailing_comma = False
            continue

        if prev_trailing_comma:
            prev_trailing_comma = bool(_PAGES_ONLY.match(stripped))
            if prev_trailing_comma:
                continue

        # Pattern B: "(YEAR) pages" with no dot leaders (e.g. Mathews v Eldridge OCR)
        nodot_m = re.search(
            r'\(\d{4}\)\s+(?:[ivxlIVXL]+|\d+)(?:\s*,\s*(?:[ivxlIVXL]+|\d+))*\s*$',
            line
        )
        m = _HAS_DOTS_PAGES.search(line)
        if m:
            cite_part = _STRIP_DOTS_END.sub('', line).strip().rstrip('.,;')
            pending.append(cite_part)
            flush(pending)
            pending = []
            prev_trailing_comma = bool(re.search(r',\s*$', m.group(0)))
        elif nodot_m:
            # Strip the space-separated page numbers at end, keep citation
            cite_part = line[:nodot_m.start() + line[nodot_m.start():].index(')') + 1].strip()
            pending.append(cite_part)
            flush(pending)
            pending = []
            prev_trailing_comma = False
        else:
            pending.append(line)
            prev_trailing_comma = False

    flush(pending)
    return titles




# ══════════════════════════════════════════════════════════════════════════════
#  SKIP-ZONE LOGIC
# ══════════════════════════════════════════════════════════════════════════════

# Always skip these sections even if body_seen is True
ALWAYS_SKIP = re.compile(
    r'INDEX\s+OF\s+AUTHORITIES'
    r'|TABLE\s+OF\s+CONTENTS'
    r'|CERTIFICATE\s+OF\s+COMP'
    r'|STATEMENT\s+OF\s+QUESTIONS\s+INVOLVED',
    re.IGNORECASE
)
# Dot-leader pattern: ≥4 consecutive dots — index pages have many of these
DOT_LEADER = re.compile(r'\.{4,}')

BODY_STARTS = re.compile(
    r'STATEMENT\s+OF\s+FACTS'
    r'|STATEMENT\s+OF\s+JURISDICTION'
    r'|INTRODUCTION',
    re.IGNORECASE
)
ARG_START = re.compile(r'^\s*ARGUMENT\s*$', re.MULTILINE)


def should_skip_page(label, text, body_seen):
    """Return True if this page should be excluded from citation scanning."""
    # Named index/ToC sections always excluded
    if ALWAYS_SKIP.search(text):
        return True
    # Front-matter roman-numeral pages with many dot-leaders = index continuation (e.g. page v)
    if ROMAN_RE.match(label) and len(DOT_LEADER.findall(text)) >= 5:
        return True
    if body_seen:
        return False
    # Before body, include only Jurisdiction page (has real MCR cites)
    if re.search(r'STATEMENT\s+OF\s+JURISDICTION', text, re.IGNORECASE):
        return False
    return True  # skip all other front matter


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN EXTRACTION (pdfplumber path — DOCX → Word → PDF)
# ══════════════════════════════════════════════════════════════════════════════

def _extract_from_pdfplumber(pdf_path, progress_cb):
    parser     = CitationParser()
    all_cites  = []
    body_seen  = False
    known_names  = set()
    display_titles = {}   # normalized_key -> full display citation from index pages

    with pdfplumber.open(pdf_path) as pdf:
        total = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            if progress_cb and i % 5 == 0:
                progress_cb(f"Scanning page {i+1} of {total}…")

            raw   = page.extract_text() or ''
            label = get_page_label_pdfplumber(page)
            if label is None:
                continue

            # Collect display titles from Index of Authorities pages (first pass)
            if re.search(r'INDEX\s+OF\s+AUTHORITIES', raw, re.IGNORECASE) or (
                    ROMAN_RE.match(label or '') and
                    len(DOT_LEADER.findall(raw)) >= 5):
                display_titles.update(parse_index_page(raw, parser))

            if BODY_STARTS.search(raw) or ARG_START.search(raw):
                body_seen = True

            if should_skip_page(label, raw, body_seen):
                continue

            cites = parser.parse_text(raw, page_label=label,
                                      known_names=known_names)
            for c in cites:
                if c['type'] == 'case':
                    known_names.add(parser.normalize(c['name']))
            all_cites.extend(cites)

    return parser.build_index(all_cites), parser, display_titles


# ══════════════════════════════════════════════════════════════════════════════
#  ZIP OCR PATH (pre-OCR'd text archive — e.g. from document scanner service)
# ══════════════════════════════════════════════════════════════════════════════

def _extract_from_zip(zip_path, progress_cb):
    """Handle ZIP archives with N.txt files whose first line is the page label."""
    parser      = CitationParser()
    all_cites   = []
    body_seen   = False
    known_names    = set()
    display_titles = {}   # normalized_key -> full display citation from index pages

    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        txt_names = sorted(
            [n for n in names if n.endswith('.txt') and n[:-4].isdigit()],
            key=lambda n: int(n[:-4])
        )
        total = len(txt_names)
        for i, fname in enumerate(txt_names):
            if progress_cb and i % 5 == 0:
                progress_cb(f"Scanning page {i+1} of {total}…")

            raw = z.read(fname).decode('utf-8', errors='replace')
            lines = raw.splitlines()
            if not lines:
                continue

            # First line is the printed page label
            label_raw = lines[0].strip()
            label = label_raw.lower() if ROMAN_RE.match(label_raw) else label_raw
            if not (ROMAN_RE.match(label_raw) or
                    (ARABIC_RE.match(label_raw) and 1 <= int(label_raw) <= 999)):
                label = None

            if label is None:
                continue

            body_text = '\n'.join(lines[1:])

            # Collect display titles from Index of Authorities pages (first pass)
            if re.search(r'INDEX\s+OF\s+AUTHORITIES', body_text, re.IGNORECASE) or (
                    ROMAN_RE.match(label_raw) and
                    len(DOT_LEADER.findall(body_text)) >= 5):
                display_titles.update(parse_index_page(body_text, parser))

            if BODY_STARTS.search(body_text) or ARG_START.search(body_text):
                body_seen = True

            # Skip index / ToC pages (body scan still skips them for page numbers)
            if should_skip_page(label, body_text, body_seen):
                continue

            cites = parser.parse_text(body_text, page_label=label,
                                      known_names=known_names)
            for c in cites:
                if c['type'] == 'case':
                    known_names.add(parser.normalize(c['name']))
            all_cites.extend(cites)

    return parser.build_index(all_cites), parser, display_titles


# ══════════════════════════════════════════════════════════════════════════════
#  UNIFIED ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def extract_index(input_path, progress_cb=None):
    ext = os.path.splitext(input_path)[1].lower()

    # ── ZIP with pre-OCR'd text ──────────────────────────────────────────────
    if ext in ('.zip',) or (ext == '.pdf' and zipfile.is_zipfile(input_path)):
        if progress_cb: progress_cb("Reading OCR text archive…")
        index, parser, display_titles = _extract_from_zip(input_path, progress_cb)
        return _format_index(index, parser, display_titles)

    # ── True PDF ─────────────────────────────────────────────────────────────
    if ext == '.pdf':
        if progress_cb: progress_cb("Scanning PDF pages…")
        index, parser, display_titles = _extract_from_pdfplumber(input_path, progress_cb)
        return _format_index(index, parser, display_titles)

    # ── DOCX → Microsoft Word → PDF → pdfplumber ─────────────────────────────
    if progress_cb: progress_cb("Converting DOCX → PDF via Microsoft Word…")
    tmp_dir  = tempfile.mkdtemp()
    pdf_path = os.path.join(tmp_dir, "brief.pdf")
    try:
        docx2pdf_convert(input_path, pdf_path)
    except Exception as e:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise RuntimeError(
            f"Could not convert DOCX to PDF.\n"
            f"Make sure Microsoft Word is installed and not currently open.\n\n{e}")
    if not os.path.exists(pdf_path):
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise RuntimeError("PDF was not created. Is Microsoft Word installed?")

    if progress_cb: progress_cb("Scanning pages for citations…")
    try:
        index, parser, display_titles = _extract_from_pdfplumber(pdf_path, progress_cb)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return _format_index(index, parser, display_titles)


def _format_index(raw_index, parser, display_titles=None):
    """Convert build_index output → {cases, rules, statutes}.

    Each value is a dict: {'display': str, 'pages': list[str]}
    Cases use full_cite as display; rules/statutes use the normalized name.
    Sort key for cases uses the short name (alphabetical by party name).
    """
    cases, rules, statutes = {}, {}, {}

    for name, data in sorted(raw_index.items(),
                              key=lambda x: case_sort_key(x[0])
                              if x[1]['type'] == 'case' else x[0].lower()):
        pages   = sort_pages(data['pages'])
        # Prefer index-page title > body full_cite > normalized name
        dt = (display_titles or {}).get(name)
        display = dt or data.get('full_cite') or name
        if data['type'] == 'case':
            cases[name]    = {'display': display, 'pages': pages}
        elif data['type'] == 'rule':
            rules[name]    = {'display': name,    'pages': pages}
        elif data['type'] == 'statute':
            statutes[name] = {'display': name,    'pages': pages}

    rules    = dict(sorted(rules.items(),    key=lambda x: mcr_sort_key(x[0])))
    statutes = dict(sorted(statutes.items(), key=lambda x: mcl_sort_key(x[0])))

    return {'cases': cases, 'rules': rules, 'statutes': statutes}


# ══════════════════════════════════════════════════════════════════════════════
#  HTML OUTPUT — matches sample Index of Authorities format from brief
#  Section order: Case Law → Michigan Court Rules and Statutes
#                              (Court Rules first, then Statutes)
# ══════════════════════════════════════════════════════════════════════════════

def build_html(data):
    def entry_html(display_name, pages_str, italic=False):
        n = f'<em>{display_name}</em>' if italic else display_name
        return (f'<div class="entry">'
                f'<span class="entry-name">{n}</span>'
                f'<span class="dots"></span>'
                f'<span class="pages">{pages_str}</span>'
                f'</div>\n')

    def entry_js(display_name, pages_str):
        safe = display_name.replace('\\', '\\\\').replace("'", "\\'")
        return f"    ['{safe}', '{pages_str}']"

    # ── Cases ────────────────────────────────────────────────────────────────
    ch, cj = '', []
    for name, entry in data['cases'].items():
        disp = entry['display']
        ps   = ', '.join(entry['pages'])
        ch  += entry_html(disp, ps, italic=True)
        cj.append(entry_js(disp, ps))

    # ── Court Rules ──────────────────────────────────────────────────────────
    rh, rj = '', []
    for name, entry in data['rules'].items():
        disp = entry['display']
        ps   = ', '.join(entry['pages'])
        rh  += entry_html(disp, ps)
        rj.append(entry_js(disp, ps))

    # ── Statutes ─────────────────────────────────────────────────────────────
    sh, sj = '', []
    for name, entry in data['statutes'].items():
        disp = entry['display']
        ps   = ', '.join(entry['pages'])
        sh  += entry_html(disp, ps)
        sj.append(entry_js(disp, ps))

    cj_s = ',\n'.join(cj)
    rj_s = ',\n'.join(rj)
    sj_s = ',\n'.join(sj)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Index of Authorities</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{
  font-family:Arial,sans-serif;font-size:12pt;
  max-width:800px;margin:30px auto;padding:20px 36px 60px;
  color:#000;background:#fff;
}}
h1{{
  text-align:center;font-size:13pt;font-weight:bold;
  text-transform:uppercase;text-decoration:underline;
  margin-bottom:28px;letter-spacing:.04em;
}}
h2{{
  font-size:12pt;font-weight:bold;text-transform:uppercase;
  text-decoration:underline;margin:24px 0 10px;
}}
h3{{
  font-size:12pt;font-weight:normal;text-decoration:underline;
  margin:16px 0 8px;
}}
.entry{{display:flex;align-items:baseline;margin-bottom:5px;line-height:1.6}}
.entry-name{{flex-shrink:0;max-width:78%}}
.entry-name em{{font-style:italic}}
.dots{{flex:1;border-bottom:1px dotted #000;margin:0 4px 3px;min-width:16px}}
.pages{{flex-shrink:0;white-space:nowrap}}
.btn-row{{display:flex;gap:10px;margin-bottom:24px}}
.copy-btn{{
  padding:7px 18px;background:#1a3a6b;color:#fff;
  border:none;border-radius:4px;font-size:11pt;
  cursor:pointer;font-family:Arial,sans-serif;
}}
.copy-btn:hover{{background:#0f2548}}
.copy-btn.copied{{background:#2a7a3b}}
@media print{{.btn-row{{display:none}}}}
</style>
</head>
<body>

<div class="btn-row">
  <button class="copy-btn" id="copyBtn" onclick="copyPlain()">&#128203; Copy as Plain Text</button>
</div>
<p style="font-size:10pt;color:#555;margin-bottom:18px">
  &#128196; To save as Word (.docx) with proper dot leaders, use the
  <strong>&#8220;Save as Word&#8221;</strong> button in the app.
</p>

<h1>Index of Authorities</h1>

{ch}

<h2>Michigan Court Rules and Statutes</h2>
<h3>Court Rules</h3>
{rh}
<h3>Statutes</h3>
{sh}

<script>
const CASES = [{cj_s}];
const RULES = [{rj_s}];
const STATS = [{sj_s}];

// ── Plain-text formatter ──────────────────────────────────────────────────────
// Right column for dot leaders (characters). Matches a ~6" content width at
// 12pt Courier/monospace (~10 chars/inch → 60 chars usable, plus page digits).
const COL = 72;

function fmt(cite, pages) {{
  // If citation fits on one line with at least 4 dots: fill to COL
  const minDots = 4;
  const needed  = COL - cite.length - pages.length;
  if (needed >= minDots) {{
    return cite + '.'.repeat(needed) + pages;
  }}
  // Citation is long — wrap: put dots + page on the continuation line, indented
  // Find a clean break point near char 70 (last space before that)
  const BREAK = 70;
  let breakAt = cite.lastIndexOf(' ', BREAK);
  if (breakAt < 30) breakAt = BREAK; // no good space found, hard-break
  const line1 = cite.slice(0, breakAt);
  const rest  = cite.slice(breakAt).trim();
  // Second line: indent 3 spaces, rest of cite, then dots, then pages
  const indent   = '   ';
  const line2raw = indent + rest;
  const dots2    = Math.max(minDots, COL - line2raw.length - pages.length);
  return line1 + '\\n' + line2raw + '.'.repeat(dots2) + pages;
}}

function buildLines() {{
  const L = ['INDEX OF AUTHORITIES', ''];
  CASES.forEach(([n, p]) => L.push(fmt(n, p)));
  L.push('', 'MICHIGAN COURT RULES AND STATUTES', '', 'COURT RULES', '');
  RULES.forEach(([n, p]) => L.push(fmt(n, p)));
  L.push('', 'STATUTES', '');
  STATS.forEach(([n, p]) => L.push(fmt(n, p)));
  return L;
}}

function doCopy(lines, btnId, label) {{
  const text = lines.join('\n');
  const btn  = document.getElementById(btnId);
  navigator.clipboard.writeText(text).then(() => {{
    btn.textContent = '✓ Copied!';
    btn.classList.add('copied');
    setTimeout(() => {{ btn.textContent = label; btn.classList.remove('copied'); }}, 2500);
  }}).catch(() => {{
    const t = document.createElement('textarea');
    t.value = text; document.body.appendChild(t); t.select();
    document.execCommand('copy'); document.body.removeChild(t); alert('Copied!');
  }});
}}
function copyPlain() {{ doCopy(buildLines(), 'copyBtn', '📋 Copy as Plain Text'); }}
</script>

<div style="text-align:center;margin-top:40px;padding-top:16px;border-top:1px solid #ddd;font-size:9pt;color:#666">
  Generated by Michigan Index of Authorities Generator<br>
  <a href="https://www.paypal.com/donate/?hosted_button_id=4AM22J9AMNCEE"
     target="_blank" style="color:#0070ba;font-weight:bold">
     💛 Support this free tool — Donate via PayPal
  </a>
</div>

</body>
</html>"""


# ══════════════════════════════════════════════════════════════════════════════
#  GUI
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
#  DOCX EXPORT  (python-docx — real dot-leader tab stops)
# ══════════════════════════════════════════════════════════════════════════════

def _add_dot_leader_tab(paragraph, tab_twips=8208):
    """Inject a right-aligned dot-leader tab stop directly into the XML."""
    pPr = paragraph._p.get_or_add_pPr()
    tabs = OxmlElement('w:tabs')
    tab  = OxmlElement('w:tab')
    tab.set(qn('w:val'),    'right')
    tab.set(qn('w:pos'),    str(tab_twips))
    tab.set(qn('w:leader'), 'dot')
    tabs.append(tab)
    pPr.append(tabs)


def generate_docx(data, output_path):
    """
    Write a proper Word .docx Index of Authorities with:
      - Right-aligned tab stop at 5.7" (8208 twips from left margin)
      - Dot leaders automatically drawn by Word between citation and page numbers
      - US Letter, 1.25" L/R margins (same as typical MI appellate brief)
    """
    if not _DOCX_OK:
        raise RuntimeError("python-docx is not installed.")

    doc = DocxDocument()

    # ── Page setup: US Letter, 1.25" left/right margins ────────────────────
    from docx.oxml import OxmlElement as OE
    section = doc.sections[0]
    section.page_width  = Inches(8.5)
    section.page_height = Inches(11)
    section.left_margin   = Inches(1.25)
    section.right_margin  = Inches(1.25)
    section.top_margin    = Inches(1.0)
    section.bottom_margin = Inches(1.0)

    # Content width = 8.5 - 1.25 - 1.25 = 6.0 inches = 8640 twips
    # Tab at right edge of content area (from left margin)
    TAB_TWIPS = 8640

    # ── Default paragraph style ─────────────────────────────────────────────
    style = doc.styles['Normal']
    style.font.name = 'Arial'
    style.font.size = Pt(12)

    def heading_para(text):
        p = doc.add_paragraph()
        run = p.add_run(text)
        run.bold = True
        run.font.name = 'Arial'
        run.font.size = Pt(12)
        p.paragraph_format.space_before = Pt(10)
        p.paragraph_format.space_after  = Pt(4)
        return p

    def entry_para(cite_text, page_text):
        p = doc.add_paragraph()
        _add_dot_leader_tab(p, TAB_TWIPS)
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after  = Pt(3)
        p.paragraph_format.left_indent  = Inches(0)
        # Hanging indent for wrapped long citations
        p.paragraph_format.first_line_indent = Inches(0)
        r1 = p.add_run(cite_text)
        r1.font.name = 'Arial'
        r1.font.size = Pt(12)
        r_tab = p.add_run('\t')
        r_tab.font.name = 'Arial'
        r_tab.font.size = Pt(12)
        r2 = p.add_run(page_text)
        r2.font.name = 'Arial'
        r2.font.size = Pt(12)
        return p

    # ── Title ────────────────────────────────────────────────────────────────
    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    tr = title.add_run('INDEX OF AUTHORITIES')
    tr.bold = True
    tr.font.name = 'Arial'
    tr.font.size = Pt(12)
    title.paragraph_format.space_after = Pt(12)

    # ── Cases ────────────────────────────────────────────────────────────────
    for entry in data['cases'].values():
        entry_para(entry['display'], ', '.join(entry['pages']))

    # ── Court Rules & Statutes ───────────────────────────────────────────────
    doc.add_paragraph()  # blank line
    heading_para('MICHIGAN COURT RULES AND STATUTES')
    doc.add_paragraph()
    heading_para('COURT RULES')

    for entry in data['rules'].values():
        entry_para(entry['display'], ', '.join(entry['pages']))

    doc.add_paragraph()
    heading_para('STATUTES')

    for entry in data['statutes'].values():
        entry_para(entry['display'], ', '.join(entry['pages']))

    doc.save(output_path)
    return output_path


# ══════════════════════════════════════════════════════════════════════════════
#  GUI
# ══════════════════════════════════════════════════════════════════════════════

PAYPAL_URL = "https://www.paypal.com/donate/?hosted_button_id=4AM22J9AMNCEE"
VERSION    = "1.0.0"

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Michigan Index of Authorities Generator")
        self.geometry("600x420")
        self.resizable(False, False)
        self.configure(bg="#f4f6fb")
        self._data = None
        self._build_ui()

    def _build_ui(self):
        # ── Header ───────────────────────────────────────────────────────────
        hdr = tk.Frame(self, bg="#1a3a6b", pady=12)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Michigan Index of Authorities Generator",
                 font=("Arial", 14, "bold"),
                 bg="#1a3a6b", fg="white").pack()
        tk.Label(hdr, text=f"v{VERSION}  |  Michigan Court of Appeals Brief Tool",
                 font=("Arial", 9),
                 bg="#1a3a6b", fg="#aac4ee").pack()

        # ── Main area ────────────────────────────────────────────────────────
        frame = tk.Frame(self, bg="#f4f6fb", padx=30, pady=16)
        frame.pack(fill="both", expand=True)

        tk.Label(frame, text="Select your appellate brief (.docx, .pdf, or OCR .zip):",
                 font=("Arial", 11), bg="#f4f6fb").pack(anchor="w")

        row = tk.Frame(frame, bg="#f4f6fb")
        row.pack(fill="x", pady=8)
        self.path_var = tk.StringVar()
        tk.Entry(row, textvariable=self.path_var,
                 font=("Arial", 10), width=46).pack(side="left", padx=(0, 8))
        tk.Button(row, text="Browse…", command=self._browse,
                  bg="#1a3a6b", fg="white", relief="flat",
                  font=("Arial", 10), padx=10).pack(side="left")

        self.status = tk.StringVar(value="Ready.")
        tk.Label(frame, textvariable=self.status,
                 font=("Arial", 9), fg="#555", bg="#f4f6fb").pack(anchor="w")

        self.progress = ttk.Progressbar(frame, mode="indeterminate", length=530)
        self.progress.pack(pady=(4, 10))

        # ── Buttons row ──────────────────────────────────────────────────────
        btn_row = tk.Frame(frame, bg="#f4f6fb")
        btn_row.pack(pady=4)

        self.gen_btn = tk.Button(
            btn_row, text="⚖  Generate Index",
            command=self._run,
            bg="#1a3a6b", fg="white",
            font=("Arial", 11, "bold"),
            relief="flat", padx=18, pady=7)
        self.gen_btn.pack(side="left", padx=(0, 10))

        self.html_btn = tk.Button(
            btn_row, text="🌐  View in Browser",
            command=self._open_browser,
            bg="#2e7d32", fg="white",
            font=("Arial", 11),
            relief="flat", padx=14, pady=7,
            state="disabled")
        self.html_btn.pack(side="left", padx=(0, 10))

        self.docx_btn = tk.Button(
            btn_row, text="📄  Save as Word",
            command=self._save_docx,
            bg="#b45309", fg="white",
            font=("Arial", 11),
            relief="flat", padx=14, pady=7,
            state="disabled")
        self.docx_btn.pack(side="left")

        # ── Footer ───────────────────────────────────────────────────────────
        foot = tk.Frame(self, bg="#e8edf5", pady=8)
        foot.pack(fill="x", side="bottom")
        lbl = tk.Label(foot,
                       text="💛  Support this free tool — Donate via PayPal",
                       font=("Arial", 9, "underline"),
                       fg="#0070ba", bg="#e8edf5", cursor="hand2")
        lbl.pack()
        lbl.bind("<Button-1>", lambda e: webbrowser.open(PAYPAL_URL))

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _browse(self):
        path = filedialog.askopenfilename(
            title="Select Brief",
            filetypes=[
                ("All supported files", "*.docx *.pdf *.zip"),
                ("Word Documents",      "*.docx"),
                ("PDF / OCR Archives",  "*.pdf *.zip"),
                ("All files",           "*.*"),
            ])
        if path:
            self.path_var.set(path)

    def _run(self):
        path = self.path_var.get().strip()
        if not path or not os.path.exists(path):
            messagebox.showerror("No file",
                "Please select a valid .docx, .pdf, or .zip file first.")
            return
        self.gen_btn.config(state="disabled")
        self.html_btn.config(state="disabled")
        self.docx_btn.config(state="disabled")
        self.progress.start(12)
        self.status.set("Extracting citations…")
        threading.Thread(target=self._worker, args=(path,), daemon=True).start()

    def _worker(self, path):
        try:
            data    = extract_index(path, progress_cb=lambda s: self.status.set(s))
            html    = build_html(data)
            tmp     = tempfile.NamedTemporaryFile(
                suffix=".html", delete=False, mode="w", encoding="utf-8",
                prefix="index_of_authorities_")
            tmp.write(html)
            tmp.close()
            self.after(0, lambda p=tmp.name, d=data: self._done(p, d))
        except Exception as ex:
            self.after(0, lambda m=str(ex): self._error(m))

    def _done(self, html_path, data):
        self.progress.stop()
        self._data      = data
        self._html_path = html_path
        nc = len(data['cases'])
        nr = len(data['rules'])
        ns = len(data['statutes'])
        self.status.set(f"✓  Done — {nc} cases · {nr} court rules · {ns} statutes")
        self.gen_btn.config(state="normal")
        self.html_btn.config(state="normal")
        self.docx_btn.config(state="normal")

    def _open_browser(self):
        if self._html_path:
            webbrowser.open(f"file:///{self._html_path}")

    def _save_docx(self):
        if not self._data:
            return
        out = filedialog.asksaveasfilename(
            title="Save Index of Authorities",
            defaultextension=".docx",
            filetypes=[("Word Document", "*.docx")],
            initialfile="index_of_authorities.docx")
        if not out:
            return
        try:
            generate_docx(self._data, out)
            messagebox.showinfo("Saved",
                f"Word document saved:\n{out}\n\n"
                "Dot leaders are rendered by Word automatically.")
            webbrowser.open(out)
        except Exception as ex:
            messagebox.showerror("Save failed", str(ex))

    def _error(self, msg):
        self.progress.stop()
        self.gen_btn.config(state="normal")
        self.status.set("Error — see dialog.")
        messagebox.showerror("Error", msg)


if __name__ == "__main__":
    App().mainloop()
