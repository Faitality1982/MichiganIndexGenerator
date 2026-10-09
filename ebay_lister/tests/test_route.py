"""
Offline tests for eBay-or-Facebook routing and the Facebook draft.

    python -m unittest discover -s tests      (from the ebay_lister folder)
"""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ebay_api                       # noqa: E402
import ebay_lister                    # noqa: E402
import listing as lst                 # noqa: E402
import route                          # noqa: E402


def routing(**overrides):
    return {"weight_lb": 4, "dims_in": [14, 10, 8], "ebay_price_est": 120,
            "ship_cost_est": 15, "free_shipping": False, "local_price_est": 40,
            **overrides}


class DecideTests(unittest.TestCase):

    def test_local_only_goes_to_facebook(self):
        channel, reasons, _ = route.decide(routing(local_only="refrigerator"))
        self.assertEqual(channel, route.FACEBOOK)
        self.assertIn("refrigerator", reasons[0])

    def test_too_heavy_goes_to_facebook(self):
        self.assertEqual(route.decide(routing(weight_lb=180))[0], route.FACEBOOK)

    def test_oversize_goes_to_facebook(self):
        channel, _, numbers = route.decide(routing(dims_in=[72, 30, 30]))   # 72 + 120
        self.assertEqual(channel, route.FACEBOOK)
        self.assertEqual(numbers["length_girth_in"], 192)

    def test_ebay_when_it_clearly_nets_more(self):
        channel, _, numbers = route.decide(routing())
        self.assertEqual(channel, route.EBAY)
        # buyer pays shipping: 120 - 0.136 * 135 - 0.40
        self.assertAlmostEqual(numbers["ebay_net"], 101.24, places=2)

    def test_free_shipping_comes_out_of_net(self):
        _, _, numbers = route.decide(routing(free_shipping=True))
        self.assertAlmostEqual(numbers["ebay_net"], 120 - 0.136 * 120 - 0.40 - 15, places=2)

    def test_cheap_item_goes_to_facebook(self):
        channel, reasons, _ = route.decide(routing(ebay_price_est=22, local_price_est=10))
        self.assertEqual(channel, route.FACEBOOK)
        self.assertIn("under $25.00", reasons[0])

    def test_close_call_asks(self):
        # eBay net 101.24 vs local 85: ahead by 16.24, but needs 25% of 85 = 21.25
        self.assertEqual(route.decide(routing(local_price_est=85))[0], route.ASK)

    def test_local_wins(self):
        self.assertEqual(route.decide(routing(local_price_est=110))[0], route.FACEBOOK)

    def test_missing_numbers_ask(self):
        channel, reasons, _ = route.decide(routing(ebay_price_est=None, weight_lb=None))
        self.assertEqual(channel, route.ASK)
        self.assertIn("ebay_price_est", reasons[0])
        self.assertIn("weight_lb", reasons[0])

    def test_config_overrides_thresholds(self):
        cfg = {"routing": {"min_ebay_net": 150}}
        self.assertEqual(route.decide(routing(), cfg)[0], route.FACEBOOK)


class FacebookDraftTests(unittest.TestCase):

    def test_html_to_text(self):
        text = route.html_to_text("<p>Brass &amp; glass lamp.</p><ul><li><b>Height:</b> 30 in</li>"
                                  "<li>Works</li></ul><p>See photos.</p>")
        self.assertEqual(text, "Brass & glass lamp.\n- Height: 30 in\n- Works\n\nSee photos.")

    def test_fields_fall_back_to_ebay_draft(self):
        listing = {"title": "Lamp", "description_html": "<p>Nice.</p>",
                   "routing": {"local_price_est": 40}, "facebook": {"condition": "Used - Good"}}
        fields = route.facebook_fields(listing)
        self.assertEqual((fields["title"], fields["price"], fields["description"]),
                         ("Lamp", 40, "Nice."))
        self.assertEqual(route.facebook_problems(fields), [])

    def test_problems(self):
        problems = route.facebook_problems(route.facebook_fields({"facebook": {"condition": "Used"}}))
        self.assertEqual(len(problems), 4)


def run_cli(*argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = ebay_lister.main(list(argv))
    return code, buf.getvalue()


class CliTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        home = self.dir / "home"
        patches = [mock.patch.object(ebay_api, "HOME", home),
                   mock.patch.object(ebay_api, "CONFIG_PATH", home / "config.json")]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.item = self.dir / "fridge"
        self.item.mkdir()
        for i in range(12):
            Image.new("RGB", (1200, 900), (i * 20, 50, 50)).save(self.item / f"IMG_{i}.jpg")

    def tearDown(self):
        self.tmp.cleanup()

    def _listing(self):
        return json.loads((self.item / lst.LISTING_FILE).read_text(encoding="utf-8"))

    def _update(self, **fields):
        data = self._listing()
        for key, value in fields.items():
            data[key] = {**data.get(key, {}), **value} if isinstance(value, dict) else value
        (self.item / lst.LISTING_FILE).write_text(json.dumps(data), encoding="utf-8")

    def test_route_and_facebook_draft_without_ebay_setup(self):
        self.assertEqual(run_cli("prep", str(self.item))[0], 0)
        self.assertIn("weight_lb", self._listing()["routing"])     # template filled in

        self._update(title="Whirlpool Top-Freezer Refrigerator 18 cu ft White",
                     description_html="<p>Works. Pickup only.</p>",
                     routing={"local_only": "full-size refrigerator", "local_price_est": 250},
                     facebook={"condition": "Used - Good", "category": "Appliances"})
        code, text = run_cli("route", str(self.item))
        self.assertEqual(code, 0)
        self.assertIn("Facebook Marketplace", text)
        self.assertEqual(self._listing()["routing"]["decision"], "facebook")

        code, text = run_cli("facebook", str(self.item))
        self.assertEqual(code, 0, text)
        fb = self.item / route.FB_DIR
        self.assertEqual(sorted(p.name for p in fb.glob("*.jpg")),
                         [f"{i:02d}.jpg" for i in range(1, 11)])          # capped at 10
        body = (fb / route.FB_TEXT).read_text(encoding="utf-8")
        self.assertIn("PRICE: 250", body)
        self.assertIn("CONDITION: Used - Good", body)
        self.assertIn("Works. Pickup only.", body)

        code, text = run_cli("status", str(self.dir))
        self.assertIn("facebook draft ready", text)

    def test_ask_keeps_users_decision(self):
        run_cli("prep", str(self.item))
        self._update(routing=routing(local_price_est=85, decision="ebay"))
        code, text = run_cli("route", str(self.item))
        self.assertIn("ASK THE USER", text)
        self.assertEqual(self._listing()["routing"]["decision"], "ebay")

    def test_publish_refuses_facebook_items(self):
        run_cli("prep", str(self.item))
        self._update(routing={"decision": "facebook"})
        ebay_api.save_config({**ebay_api.CONFIG_TEMPLATE, "client_id": "a",
                              "client_secret": "b", "ru_name": "c"})
        code, text = run_cli("publish", str(self.item), "--yes")
        self.assertEqual(code, 1)
        self.assertIn("routed to Facebook", text)


if __name__ == "__main__":
    unittest.main()
