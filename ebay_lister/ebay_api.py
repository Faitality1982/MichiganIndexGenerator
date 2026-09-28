"""
eBay API client for ebay_lister.

Only what listing one-off items needs:
  - OAuth: one-time user consent (authorization code), refresh, app tokens
  - Taxonomy API:  category suggestions, item specifics per category
  - Metadata API:  allowed item conditions per category
  - Account API:   business policies (shipping / payment / return)
  - Browse API:    active listings, used as a price reference
  - Media API:     photo upload (replaces Trading UploadSiteHostedPictures,
                   which eBay decommissions 2026-09-30)
  - Trading API:   VerifyAddItem / AddItem. Listings created this way behave
                   like Seller Hub listings and stay editable there.
"""

import base64
import json
import os
import time
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

import requests


# ══════════════════════════════════════════════════════════════════════════════
#  CONFIG
# ══════════════════════════════════════════════════════════════════════════════

# Secrets live outside the repo so they can't be committed by accident.
HOME = Path(os.environ.get("EBAY_LISTER_HOME") or Path.home() / ".ebay_lister")
CONFIG_PATH = HOME / "config.json"
TOKEN_PATH = HOME / "token.json"

CONFIG_TEMPLATE = {
    "environment": "production",      # "production" or "sandbox"
    "client_id": "",                  # App ID (Client ID)
    "client_secret": "",              # Cert ID (Client Secret)
    "ru_name": "",                    # RuName (eBay Redirect URL name)
    "marketplace_id": "EBAY_US",
    "site_id": 0,                     # Trading API site: 0 = US
    "country": "US",
    "currency": "USD",
    "postal_code": "",                # where the item ships from
    "location": "",                   # e.g. "Port Huron, MI"
    "policies": {"shipping": "", "payment": "", "return": ""},
    "description_footer_html": "",
}

# Environment variables win over config.json (useful for cloud sessions).
ENV_OVERRIDES = {
    "client_id": "EBAY_CLIENT_ID",
    "client_secret": "EBAY_CLIENT_SECRET",
    "ru_name": "EBAY_RUNAME",
}

HOSTS = {
    "production": {
        "auth": "https://auth.ebay.com",
        "api": "https://api.ebay.com",
        "media": "https://apim.ebay.com",
        "web": "https://www.ebay.com",
    },
    "sandbox": {
        "auth": "https://auth.sandbox.ebay.com",
        "api": "https://api.sandbox.ebay.com",
        "media": "https://api.sandbox.ebay.com",
        "web": "https://sandbox.ebay.com",
    },
}

SCOPES = [
    "https://api.ebay.com/oauth/api_scope",
    "https://api.ebay.com/oauth/api_scope/sell.inventory",   # Media API
    "https://api.ebay.com/oauth/api_scope/sell.account",     # business policies
]
APP_SCOPE = "https://api.ebay.com/oauth/api_scope"

TRADING_COMPAT_LEVEL = "1477"
TRADING_NS = "urn:ebay:apis:eBLBaseComponents"


class EbayError(Exception):
    """Anything that should stop the command and be shown to the user as-is."""


def load_config():
    if not CONFIG_PATH.exists():
        raise EbayError(f"No config found at {CONFIG_PATH}\n"
                        f"Run:  python ebay_lister.py setup")
    raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    cfg = {**CONFIG_TEMPLATE, **raw}
    cfg["policies"] = {**CONFIG_TEMPLATE["policies"], **raw.get("policies", {})}
    for key, var in ENV_OVERRIDES.items():
        if os.environ.get(var):
            cfg[key] = os.environ[var]
    if cfg["environment"] not in HOSTS:
        raise EbayError(f'config.json "environment" must be "production" or '
                        f'"sandbox", not "{cfg["environment"]}"')
    return cfg


def save_config(cfg):
    HOME.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


def _load_tokens():
    if TOKEN_PATH.exists():
        return json.loads(TOKEN_PATH.read_text(encoding="utf-8"))
    return {}


def _save_tokens(tokens):
    HOME.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(json.dumps(tokens, indent=2) + "\n", encoding="utf-8")


def _rest_error_text(resp):
    """Pull the human-readable message out of an eBay REST/OAuth error body."""
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:500] or f"HTTP {resp.status_code}"
    if "errors" in body:
        return "; ".join(e.get("longMessage") or e.get("message") or str(e)
                         for e in body["errors"])
    if "error" in body:  # OAuth endpoint format
        return f'{body["error"]}: {body.get("error_description", "")}'
    return json.dumps(body)[:500]


def _strip_ns(root):
    for el in root.iter():
        if isinstance(el.tag, str) and el.tag.startswith("{"):
            el.tag = el.tag.split("}", 1)[1]
    return root


# ══════════════════════════════════════════════════════════════════════════════
#  CLIENT
# ══════════════════════════════════════════════════════════════════════════════

class EbayClient:

    def __init__(self, cfg, session=None):
        self.cfg = cfg
        self.env = cfg["environment"]
        self.hosts = HOSTS[self.env]
        self.http = session or requests.Session()
        self._app_token = None
        self._tree_id = None

    # ── OAuth ────────────────────────────────────────────────────────────────

    def _require_keys(self):
        missing = [k for k in ("client_id", "client_secret", "ru_name")
                   if not self.cfg.get(k)]
        if missing:
            raise EbayError(f"Missing {', '.join(missing)} in {CONFIG_PATH}")

    def consent_url(self):
        self._require_keys()
        query = urllib.parse.urlencode({
            "client_id": self.cfg["client_id"],
            "redirect_uri": self.cfg["ru_name"],
            "response_type": "code",
            "scope": " ".join(SCOPES),
        }, quote_via=urllib.parse.quote)
        return f'{self.hosts["auth"]}/oauth2/authorize?{query}'

    def _token_request(self, data):
        self._require_keys()
        basic = base64.b64encode(
            f'{self.cfg["client_id"]}:{self.cfg["client_secret"]}'.encode()).decode()
        resp = self.http.post(
            f'{self.hosts["api"]}/identity/v1/oauth2/token',
            headers={"Authorization": f"Basic {basic}",
                     "Content-Type": "application/x-www-form-urlencoded"},
            data=data, timeout=30)
        if resp.status_code != 200:
            raise EbayError(f"eBay sign-in failed: {_rest_error_text(resp)}")
        return resp.json()

    @staticmethod
    def extract_code(redirect_url_or_code):
        """Accept the full URL eBay redirected to, or just the code value."""
        text = redirect_url_or_code.strip()
        if "code=" in text:
            params = urllib.parse.parse_qs(urllib.parse.urlparse(text).query)
            if "code" not in params:  # pasted "code=...&expires_in=..." only
                params = urllib.parse.parse_qs(text.split("?", 1)[-1])
            codes = params.get("code")
            if not codes:
                raise EbayError("Couldn't find code= in the pasted URL.")
            return codes[0]
        return urllib.parse.unquote(text)

    def exchange_code(self, redirect_url_or_code):
        code = self.extract_code(redirect_url_or_code)
        body = self._token_request({
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.cfg["ru_name"],
        })
        now = time.time()
        tokens = _load_tokens()
        tokens[self.env] = {
            "refresh_token": body["refresh_token"],
            "refresh_token_expires_at": now + body.get("refresh_token_expires_in", 0),
            "access_token": body["access_token"],
            "access_token_expires_at": now + body.get("expires_in", 0),
        }
        _save_tokens(tokens)
        return tokens[self.env]

    def refresh_token_days_left(self):
        entry = _load_tokens().get(self.env)
        if not entry:
            return None
        return (entry.get("refresh_token_expires_at", 0) - time.time()) / 86400

    def user_token(self):
        refresh_env = os.environ.get("EBAY_REFRESH_TOKEN")
        tokens = _load_tokens()
        entry = tokens.get(self.env) or {}
        if refresh_env and entry.get("refresh_token") != refresh_env:
            entry = {"refresh_token": refresh_env}
        if not entry.get("refresh_token"):
            raise EbayError("Not signed in to eBay. Run:  python ebay_lister.py auth")
        if entry.get("access_token_expires_at", 0) - time.time() > 120:
            return entry["access_token"]
        body = self._token_request({
            "grant_type": "refresh_token",
            "refresh_token": entry["refresh_token"],
            "scope": " ".join(SCOPES),
        })
        entry["access_token"] = body["access_token"]
        entry["access_token_expires_at"] = time.time() + body.get("expires_in", 0)
        tokens[self.env] = entry
        _save_tokens(tokens)
        return entry["access_token"]

    def app_token(self):
        if self._app_token and self._app_token[1] - time.time() > 120:
            return self._app_token[0]
        body = self._token_request({"grant_type": "client_credentials",
                                    "scope": APP_SCOPE})
        self._app_token = (body["access_token"], time.time() + body.get("expires_in", 0))
        return self._app_token[0]

    # ── REST helpers ─────────────────────────────────────────────────────────

    def _get(self, url, token, params=None, headers=None):
        resp = self.http.get(url, params=params, timeout=30, headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            **(headers or {})})
        if resp.status_code == 204:
            return {}
        if resp.status_code >= 400:
            raise EbayError(f"eBay API error ({resp.status_code}): {_rest_error_text(resp)}")
        return resp.json()

    # ── Taxonomy / Metadata ──────────────────────────────────────────────────

    def category_tree_id(self):
        if self._tree_id is None:
            body = self._get(f'{self.hosts["api"]}/commerce/taxonomy/v1/get_default_category_tree_id',
                             self.app_token(), {"marketplace_id": self.cfg["marketplace_id"]})
            self._tree_id = body["categoryTreeId"]
        return self._tree_id

    def category_suggestions(self, query):
        """[(category_id, name, breadcrumb)] best match first."""
        body = self._get(
            f'{self.hosts["api"]}/commerce/taxonomy/v1/category_tree/'
            f'{self.category_tree_id()}/get_category_suggestions',
            self.app_token(), {"q": query})
        out = []
        for s in body.get("categorySuggestions", []):
            ancestors = [a["categoryName"] for a in
                         sorted(s.get("categoryTreeNodeAncestors", []),
                                key=lambda a: a.get("categoryTreeNodeLevel", 0))]
            name = s["category"]["categoryName"]
            out.append((s["category"]["categoryId"], name, " > ".join(ancestors + [name])))
        return out

    def item_aspects(self, category_id):
        """Item specifics for a leaf category, as simple dicts."""
        body = self._get(
            f'{self.hosts["api"]}/commerce/taxonomy/v1/category_tree/'
            f'{self.category_tree_id()}/get_item_aspects_for_category',
            self.app_token(), {"category_id": category_id})
        out = []
        for a in body.get("aspects", []):
            c = a.get("aspectConstraint", {})
            out.append({
                "name": a["localizedAspectName"],
                "required": bool(c.get("aspectRequired")),
                "usage": c.get("aspectUsage", ""),                   # RECOMMENDED / OPTIONAL
                "mode": c.get("aspectMode", "FREE_TEXT"),            # or SELECTION_ONLY
                "multi": c.get("itemToAspectCardinality") == "MULTI",
                "max_length": c.get("aspectMaxLength"),
                "values": [v["localizedValue"] for v in a.get("aspectValues", [])],
            })
        return out

    def condition_policy(self, category_id):
        """(condition_required, [(condition_id, description)])"""
        body = self._get(
            f'{self.hosts["api"]}/sell/metadata/v1/marketplace/'
            f'{self.cfg["marketplace_id"]}/get_item_condition_policies',
            self.app_token(), {"filter": f"categoryIds:{{{category_id}}}"})
        policies = body.get("itemConditionPolicies", [])
        if not policies:
            return False, []
        p = policies[0]
        return (bool(p.get("itemConditionRequired")),
                [(int(c["conditionId"]), c.get("conditionDescription", ""))
                 for c in p.get("itemConditions", [])])

    # ── Account (business policies) ──────────────────────────────────────────

    def business_policies(self):
        token = self.user_token()
        base = f'{self.hosts["api"]}/sell/account/v1'
        params = {"marketplace_id": self.cfg["marketplace_id"]}
        ship = self._get(f"{base}/fulfillment_policy", token, params)
        pay = self._get(f"{base}/payment_policy", token, params)
        ret = self._get(f"{base}/return_policy", token, params)
        return {
            "shipping": [(p["fulfillmentPolicyId"], p.get("name", ""))
                         for p in ship.get("fulfillmentPolicies", [])],
            "payment": [(p["paymentPolicyId"], p.get("name", ""))
                        for p in pay.get("paymentPolicies", [])],
            "return": [(p["returnPolicyId"], p.get("name", ""))
                       for p in ret.get("returnPolicies", [])],
        }

    # ── Browse (price reference) ─────────────────────────────────────────────

    def search_active(self, query, category_id=None, condition_id=None, limit=50):
        """Active fixed-price listings: [(price, currency, title, url)]."""
        filters = ["buyingOptions:{FIXED_PRICE}"]
        if condition_id:
            filters.append(f"conditionIds:{{{condition_id}}}")
        params = {"q": query[:100], "limit": limit, "filter": ",".join(filters)}
        if category_id:
            params["category_ids"] = category_id
        body = self._get(f'{self.hosts["api"]}/buy/browse/v1/item_summary/search',
                         self.app_token(), params,
                         {"X-EBAY-C-MARKETPLACE-ID": self.cfg["marketplace_id"]})
        out = []
        for it in body.get("itemSummaries", []):
            price = it.get("price") or {}
            if price.get("value"):
                out.append((float(price["value"]), price.get("currency", ""),
                            it.get("title", ""), it.get("itemWebUrl", "")))
        return out, body.get("total", len(out))

    # ── Media (photos) ───────────────────────────────────────────────────────

    def upload_photo(self, path):
        """Upload one image to eBay Picture Services. Returns (url, expires)."""
        with open(path, "rb") as fh:
            resp = self.http.post(
                f'{self.hosts["media"]}/commerce/media/v1_beta/image/create_image_from_file',
                headers={"Authorization": f"Bearer {self.user_token()}"},
                files={"image": (Path(path).name, fh, "image/jpeg")},
                timeout=120)
        if resp.status_code not in (200, 201):
            raise EbayError(f"Photo upload failed for {Path(path).name} "
                            f"({resp.status_code}): {_rest_error_text(resp)}")
        body = resp.json() if resp.content else {}
        if not body.get("imageUrl"):
            # Some responses only carry the Location header; fetch the image record.
            location = resp.headers.get("Location")
            if not location:
                raise EbayError(f"Photo upload for {Path(path).name} returned no image URL")
            body = self._get(location, self.user_token())
        return body["imageUrl"], body.get("expirationDate", "")

    # ── Trading ──────────────────────────────────────────────────────────────

    def trading(self, call_name, xml_body):
        """POST a Trading API call. Returns (response_root, warnings).
        Raises EbayError on Failure, with any duplicate-listing ItemID attached."""
        resp = self.http.post(
            f'{self.hosts["api"]}/ws/api.dll',
            data=xml_body, timeout=120,
            headers={
                "X-EBAY-API-COMPATIBILITY-LEVEL": TRADING_COMPAT_LEVEL,
                "X-EBAY-API-CALL-NAME": call_name,
                "X-EBAY-API-SITEID": str(self.cfg["site_id"]),
                "X-EBAY-API-IAF-TOKEN": self.user_token(),
                "Content-Type": "text/xml; charset=utf-8",
            })
        try:
            root = _strip_ns(ET.fromstring(resp.content))
        except ET.ParseError:
            raise EbayError(f"{call_name} returned HTTP {resp.status_code}: {resp.text[:500]}")
        errors, warnings = parse_trading_errors(root)
        if root.findtext("Ack") not in ("Success", "Warning"):
            err = EbayError(f"{call_name} failed:\n" + "\n".join(
                f"  [{e['code']}] {e['message']}" for e in errors or warnings))
            err.duplicate_item_id = duplicate_item_id(errors)
            raise err
        return root, warnings


def parse_trading_errors(root):
    """Split Trading API <Errors> into (errors, warnings)."""
    errors, warnings = [], []
    for e in root.findall("Errors"):
        entry = {
            "code": e.findtext("ErrorCode", ""),
            "message": e.findtext("LongMessage") or e.findtext("ShortMessage", ""),
            "params": [p.findtext("Value", "") for p in e.findall("ErrorParameters")],
        }
        (warnings if e.findtext("SeverityCode") == "Warning" else errors).append(entry)
    return errors, warnings


def duplicate_item_id(errors):
    """eBay error 488 = this Item.UUID already created a listing; return its ItemID."""
    for e in errors:
        if e["code"] == "488":
            for value in e["params"]:
                if value.isdigit() and len(value) >= 9:
                    return value
    return None


def parse_fees(root):
    """Non-zero fees from an AddItem / VerifyAddItem response: [(name, amount, currency)]."""
    out = []
    for fee in root.findall("Fees/Fee"):
        amount_el = fee.find("Fee")
        if amount_el is None or not amount_el.text:
            continue
        amount = float(amount_el.text)
        if amount:
            out.append((fee.findtext("Name", ""), amount, amount_el.get("currencyID", "")))
    return out
