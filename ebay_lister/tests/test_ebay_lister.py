"""
Offline tests: photo prep, validation, request XML, response parsing, and a full
prep -> category -> verify -> publish run against a fake eBay.

    python -m unittest discover -s tests      (from the ebay_lister folder)
"""

import contextlib
import io
import json
import sys
import tempfile
import time
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ebay_api                       # noqa: E402
import ebay_lister                    # noqa: E402
import listing as lst                 # noqa: E402
from ebay_api import EbayClient  # noqa: E402

CFG = {**ebay_api.CONFIG_TEMPLATE,
       "client_id": "app", "client_secret": "secret", "ru_name": "ru",
       "postal_code": "48060", "location": "Port Huron, MI",
       "policies": {"shipping": "111", "payment": "222", "return": "333"},
       "description_footer_html": "<p>Ships in 2 business days.</p>"}


def make_photo(path, size=(2400, 1800), orientation=None, gps=False, mode="RGB"):
    img = Image.new(mode, size, (200, 30, 30, 128) if mode == "RGBA" else (200, 30, 30))
    exif = Image.Exif()
    if orientation:
        exif[0x0112] = orientation
    if gps:
        exif[0x8825] = {2: (42.0, 58.0, 0.0), 1: "N"}
    kwargs = {"exif": exif.tobytes()} if (orientation or gps) else {}
    img.save(path, **kwargs)


def good_listing(**overrides):
    return {**lst.LISTING_TEMPLATE,
            "title": "Stiffel Brass Table Lamp 30 in Tested Working",
            "category_id": "112581", "category_name": "Home > Lamps",
            "condition_id": 3000, "condition_description": "Light wear on base.",
            "item_specifics": {"Brand": "Stiffel", "Features": ["3-Way", "Dimmable"]},
            "description_html": "<p>Brass & glass lamp <b>works</b>.</p>",
            "price": 89.5, **overrides}


class PhotoTests(unittest.TestCase):

    def test_prepare_rotates_resizes_strips_metadata(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            make_photo(d / "IMG_10.jpg", orientation=6, gps=True)   # rotated 90
            make_photo(d / "IMG_9.png", size=(800, 600), mode="RGBA")
            make_photo(d / "IMG_9.jpg", size=(300, 200))           # name clash, tiny
            (d / "notes.txt").write_text("not a photo")

            results = lst.prepare_photos(d)
            names = [r[1] for r in results]
            self.assertEqual(names, ["IMG_9.jpg", "IMG_9_2.jpg", "IMG_10.jpg"])  # natural order
            sizes = dict((r[1], r[2]) for r in results)
            self.assertEqual(sizes["IMG_10.jpg"], (1200, 1600))    # upright, long side 1600
            self.assertEqual(sizes["IMG_9.jpg"], (300, 200))       # never upscaled
            self.assertEqual(sizes["IMG_9_2.jpg"], (800, 600))     # the .png

            with Image.open(d / "prepared" / "IMG_10.jpg") as img:
                self.assertEqual(img.format, "JPEG")
                self.assertEqual(len(img.getexif()), 0)            # GPS gone
                self.assertNotIn("exif", img.info)
            with Image.open(d / "prepared" / "IMG_9_2.jpg") as img:
                self.assertEqual(img.mode, "RGB")                  # alpha flattened

            # prepared/ is rebuilt each run; originals untouched
            lst.prepare_photos(d)
            self.assertEqual(len(list((d / "prepared").glob("*.jpg"))), 3)
            self.assertTrue((d / "IMG_10.jpg").exists())

    def test_heic_without_plugin_gives_clear_error(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "IMG_1.HEIC").write_bytes(b"fake")
            with mock.patch.object(lst, "HEIC_OK", False):
                with self.assertRaisesRegex(RuntimeError, "pillow-heif"):
                    lst.prepare_photos(d)


class ValidationTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        make_photo(self.dir / "a.jpg")
        lst.prepare_photos(self.dir)

    def tearDown(self):
        self.tmp.cleanup()

    def test_good_listing_passes(self):
        errors, warnings = lst.validate(self.dir, good_listing(), CFG)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_problems_are_reported(self):
        bad = good_listing(title="x" * 81, price=None, category_id="",
                           listing_type="Chinese", duration="GTC",
                           item_specifics={"Brand": ""},
                           photos=["missing.jpg"], seller_notes=["confirm height"])
        cfg = {**CFG, "postal_code": "", "policies": {"shipping": "", "payment": "2", "return": "3"}}
        errors, warnings = lst.validate(self.dir, bad, cfg)
        text = "\n".join(errors)
        for expected in ("81 characters", "price is not set", "category_id is empty",
                         "auction duration", 'Brand" has an empty value',
                         "photo not found", "postal_code", "no shipping policy"):
            self.assertIn(expected, text)
        self.assertIn("unresolved note: confirm height", warnings)

    def test_bool_price_rejected(self):
        errors, _ = lst.validate(self.dir, good_listing(price=True), CFG)
        self.assertTrue(any("price" in e for e in errors))


class XmlTests(unittest.TestCase):

    def parse(self, body):
        return ebay_api._strip_ns(ET.fromstring(body))

    def test_add_item_xml(self):
        body = lst.build_item_xml("AddItem", good_listing(), CFG,
                                  ["https://i.ebayimg.com/1.jpg", "https://i.ebayimg.com/2.jpg"],
                                  "A" * 32)
        root = self.parse(body)
        self.assertEqual(root.tag, "AddItemRequest")
        item = root.find("Item")
        self.assertEqual(item.findtext("Title"), "Stiffel Brass Table Lamp 30 in Tested Working")
        self.assertEqual(item.findtext("StartPrice"), "89.50")
        self.assertEqual(item.find("StartPrice").get("currencyID"), "USD")
        self.assertEqual(item.findtext("PrimaryCategory/CategoryID"), "112581")
        self.assertEqual(item.findtext("ConditionID"), "3000")
        self.assertEqual(item.findtext("ConditionDescription"), "Light wear on base.")
        self.assertEqual(item.findtext("ListingDuration"), "GTC")
        self.assertEqual(item.findtext("BestOfferDetails/BestOfferEnabled"), "true")
        self.assertEqual(item.findtext("UUID"), "A" * 32)
        self.assertEqual(item.findtext("PostalCode"), "48060")
        # HTML survives the XML round trip exactly, footer appended
        self.assertEqual(item.findtext("Description"),
                         "<p>Brass & glass lamp <b>works</b>.</p>\n<p>Ships in 2 business days.</p>")
        self.assertEqual([p.text for p in item.findall("PictureDetails/PictureURL")],
                         ["https://i.ebayimg.com/1.jpg", "https://i.ebayimg.com/2.jpg"])
        features = [n for n in item.findall("ItemSpecifics/NameValueList")
                    if n.findtext("Name") == "Features"][0]
        self.assertEqual([v.text for v in features.findall("Value")], ["3-Way", "Dimmable"])
        self.assertEqual(item.findtext("SellerProfiles/SellerShippingProfile/ShippingProfileID"), "111")
        self.assertEqual(item.findtext("SellerProfiles/SellerPaymentProfile/PaymentProfileID"), "222")
        self.assertEqual(item.findtext("SellerProfiles/SellerReturnProfile/ReturnProfileID"), "333")

    def test_new_condition_and_no_condition(self):
        item = self.parse(lst.build_item_xml("VerifyAddItem", good_listing(condition_id=1000),
                                             CFG, ["u"], "B" * 32)).find("Item")
        self.assertIsNone(item.find("ConditionDescription"))
        item = self.parse(lst.build_item_xml("VerifyAddItem", good_listing(condition_id=None),
                                             CFG, ["u"], "B" * 32)).find("Item")
        self.assertIsNone(item.find("ConditionID"))

    def test_trading_response_parsing(self):
        ns = 'xmlns="urn:ebay:apis:eBLBaseComponents"'
        ok = self.parse(f"""<VerifyAddItemResponse {ns}><Ack>Warning</Ack>
            <Errors><ShortMessage>s</ShortMessage><LongMessage>Title has caps</LongMessage>
            <ErrorCode>123</ErrorCode><SeverityCode>Warning</SeverityCode></Errors>
            <Fees><Fee><Name>ListingFee</Name><Fee currencyID="USD">0.35</Fee></Fee>
            <Fee><Name>GalleryFee</Name><Fee currencyID="USD">0.0</Fee></Fee></Fees>
            </VerifyAddItemResponse>""")
        self.assertEqual(ebay_api.parse_fees(ok), [("ListingFee", 0.35, "USD")])
        errors, warnings = ebay_api.parse_trading_errors(ok)
        self.assertEqual((errors, warnings[0]["message"]), ([], "Title has caps"))

        dup = self.parse(f"""<AddItemResponse {ns}><Ack>Failure</Ack>
            <Errors><LongMessage>Duplicate UUID</LongMessage><ErrorCode>488</ErrorCode>
            <SeverityCode>Error</SeverityCode>
            <ErrorParameters ParamID="0"><Value>true</Value></ErrorParameters>
            <ErrorParameters ParamID="1"><Value>256789012345</Value></ErrorParameters>
            </Errors></AddItemResponse>""")
        errors, _ = ebay_api.parse_trading_errors(dup)
        self.assertEqual(ebay_api.duplicate_item_id(errors), "256789012345")


class AuthTests(unittest.TestCase):

    def test_extract_code(self):
        url = ("https://signin.ebay.com/ws/eBayISAPI.dll?ThirdPartyAuthSucessFailure"
               "&isAuthSuccessful=true&code=v%5E1.1%23i%5E1%23p&expires_in=299")
        self.assertEqual(EbayClient.extract_code(url), "v^1.1#i^1#p")
        self.assertEqual(EbayClient.extract_code("code=v%5E1.1&expires_in=299"), "v^1.1")
        self.assertEqual(EbayClient.extract_code("v%5E1.1%23i"), "v^1.1#i")

    def test_consent_url(self):
        url = EbayClient(CFG).consent_url()
        self.assertTrue(url.startswith("https://auth.ebay.com/oauth2/authorize?client_id=app"))
        self.assertIn("redirect_uri=ru", url)
        self.assertIn("sell.account", url)
        self.assertNotIn("+", url)   # scopes space-separated as %20


# ══════════════════════════════════════════════════════════════════════════════
#  END TO END AGAINST A FAKE EBAY
# ══════════════════════════════════════════════════════════════════════════════

class FakeResponse:
    def __init__(self, status=200, body=None, text=None, headers=None):
        self.status_code = status
        self._body = body
        self.text = text if text is not None else json.dumps(body or {})
        self.content = self.text.encode()
        self.headers = headers or {}

    def json(self):
        return self._body if self._body is not None else json.loads(self.text)


class FakeEbay:
    """Routes requests by URL; records Trading calls and uploads."""
    NS = 'xmlns="urn:ebay:apis:eBLBaseComponents"'

    def __init__(self):
        self.trading_calls, self.uploads, self.token_grants = [], [], []

    def get(self, url, params=None, headers=None, timeout=None):
        if url.endswith("get_default_category_tree_id"):
            return FakeResponse(body={"categoryTreeId": "0"})
        if url.endswith("get_category_suggestions"):
            return FakeResponse(body={"categorySuggestions": [
                {"category": {"categoryId": "112581", "categoryName": "Lamps"},
                 "categoryTreeNodeAncestors": [
                     {"categoryName": "Lamps, Lighting", "categoryTreeNodeLevel": 2},
                     {"categoryName": "Home & Garden", "categoryTreeNodeLevel": 1}]}]})
        if url.endswith("get_item_aspects_for_category"):
            return FakeResponse(body={"aspects": [
                {"localizedAspectName": "Brand",
                 "aspectConstraint": {"aspectRequired": True, "aspectMode": "FREE_TEXT"}},
                {"localizedAspectName": "Type",
                 "aspectConstraint": {"aspectRequired": True, "aspectMode": "SELECTION_ONLY"},
                 "aspectValues": [{"localizedValue": "Table Lamp"}]}]})
        if url.endswith("get_item_condition_policies"):
            assert params["filter"] == "categoryIds:{112581}", params
            return FakeResponse(body={"itemConditionPolicies": [{
                "itemConditionRequired": True,
                "itemConditions": [{"conditionId": "1000", "conditionDescription": "New"},
                                   {"conditionId": "3000", "conditionDescription": "Used"}]}]})
        if url.endswith("item_summary/search"):
            return FakeResponse(body={"total": 2, "itemSummaries": [
                {"title": "Lamp A", "price": {"value": "60.00", "currency": "USD"}, "itemWebUrl": "u1"},
                {"title": "Lamp B", "price": {"value": "120.00", "currency": "USD"}, "itemWebUrl": "u2"}]})
        raise AssertionError(f"unexpected GET {url}")

    def post(self, url, data=None, files=None, headers=None, timeout=None):
        if url.endswith("/identity/v1/oauth2/token"):
            self.token_grants.append(data["grant_type"])
            return FakeResponse(body={"access_token": f"tok-{data['grant_type']}", "expires_in": 7200})
        if url.endswith("create_image_from_file"):
            assert headers["Authorization"] == "Bearer tok-refresh_token"
            self.uploads.append(files["image"][0])
            return FakeResponse(201, body={"imageUrl": f"https://i.ebayimg.com/{files['image'][0]}",
                                           "expirationDate": "2099-01-01T00:00:00.000Z"})
        if url.endswith("/ws/api.dll"):
            call = headers["X-EBAY-API-CALL-NAME"]
            self.trading_calls.append((call, data))
            fees = '<Fees><Fee><Name>ListingFee</Name><Fee currencyID="USD">0.35</Fee></Fee></Fees>'
            item = "<ItemID>256700000001</ItemID>" if call == "AddItem" else ""
            return FakeResponse(text=f"<{call}Response {self.NS}><Ack>Success</Ack>{item}{fees}"
                                     f"</{call}Response>")
        raise AssertionError(f"unexpected POST {url}")


class EndToEndTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        home = root / "home"
        home.mkdir()
        (home / "config.json").write_text(json.dumps(CFG))
        (home / "token.json").write_text(json.dumps({"production": {
            "refresh_token": "r", "refresh_token_expires_at": time.time() + 9e6}}))
        self.item = root / "brass-lamp"
        self.item.mkdir()
        make_photo(self.item / "IMG_2.jpg")
        make_photo(self.item / "IMG_1.jpg")
        self.fake = FakeEbay()
        self.patches = [
            mock.patch.object(ebay_api, "HOME", home),
            mock.patch.object(ebay_api, "CONFIG_PATH", home / "config.json"),
            mock.patch.object(ebay_api, "TOKEN_PATH", home / "token.json"),
            mock.patch.object(ebay_api.requests, "Session", lambda: self.fake),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def run_cli(self, *argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), mock.patch.object(sys.stdin, "isatty", lambda: False):
            code = ebay_lister.main(list(argv))
        return code, buf.getvalue()

    def test_full_flow(self):
        code, output = self.run_cli("prep", str(self.item))
        self.assertEqual(code, 0, output)
        self.assertIn("Created listing.json", output)

        listing = lst.load_listing(self.item)
        listing.update(good_listing(category_id="", item_specifics={"Brand": "Stiffel"}))
        lst.save_listing(self.item, listing)

        code, output = self.run_cli("category", str(self.item))
        self.assertIn("[112581] Home & Garden > Lamps, Lighting > Lamps", output)
        code, output = self.run_cli("category", str(self.item), "--pick", "1")
        self.assertEqual(code, 0, output)
        self.assertIn("Brand: = Stiffel", output)
        self.assertIn("Type: MISSING", output)
        self.assertIn("e.g. Table Lamp", output)
        self.assertIn("1 required item specific(s) missing", output)
        self.assertEqual(lst.load_listing(self.item)["category_id"], "112581")

        code, output = self.run_cli("comps", str(self.item))
        self.assertIn("median $90.00", output)
        self.assertIn("ASKING prices", output)

        code, output = self.run_cli("verify", str(self.item))
        self.assertEqual(code, 0, output)
        self.assertIn("Listing fees: $0.35", output)
        self.assertEqual(self.fake.uploads, ["IMG_1.jpg", "IMG_2.jpg"])
        self.assertEqual([c for c, _ in self.fake.trading_calls], ["VerifyAddItem"])

        # publish without --yes in a non-interactive shell must not list
        code, output = self.run_cli("publish", str(self.item))
        self.assertEqual(code, 2)
        self.assertNotIn("AddItem", [c for c, _ in self.fake.trading_calls])

        code, output = self.run_cli("publish", str(self.item), "--yes")
        self.assertEqual(code, 0, output)
        self.assertIn("LISTED: https://www.ebay.com/itm/256700000001", output)
        self.assertEqual(self.fake.uploads, ["IMG_1.jpg", "IMG_2.jpg"])  # cached, not re-sent

        # verify and AddItem carried the same UUID
        uuids = {ebay_api._strip_ns(ET.fromstring(body)).findtext("Item/UUID")
                 for _, body in self.fake.trading_calls}
        self.assertEqual(len(uuids), 1)

        code, output = self.run_cli("publish", str(self.item), "--yes")
        self.assertIn("Already listed", output)
        self.assertEqual([c for c, _ in self.fake.trading_calls].count("AddItem"), 1)

        code, output = self.run_cli("status", str(self.item.parent))
        self.assertIn("$89.50", output)
        self.assertIn("256700000001", output)

    def test_validation_blocks_before_any_upload(self):
        self.run_cli("prep", str(self.item))
        code, output = self.run_cli("verify", str(self.item))
        self.assertEqual(code, 2)
        self.assertIn("title is empty", output)
        self.assertEqual(self.fake.uploads, [])

    def test_failure_message_from_ebay(self):
        self.run_cli("prep", str(self.item))
        lst.save_listing(self.item, good_listing())
        fail = FakeResponse(text=f'<VerifyAddItemResponse {FakeEbay.NS}><Ack>Failure</Ack>'
                                 f'<Errors><LongMessage>Item specific Type is missing.</LongMessage>'
                                 f'<ErrorCode>21919303</ErrorCode><SeverityCode>Error</SeverityCode>'
                                 f'</Errors></VerifyAddItemResponse>')
        original = self.fake.post
        self.fake.post = lambda url, **kw: fail if url.endswith("api.dll") else original(url, **kw)
        code, output = self.run_cli("verify", str(self.item))
        self.assertEqual(code, 1)
        self.assertIn("[21919303] Item specific Type is missing.", output)


if __name__ == "__main__":
    unittest.main()
