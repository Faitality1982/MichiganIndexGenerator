"""
Offline tests: choosing the shipping policy by packed weight.

    python -m unittest discover -s tests      (from the ebay_lister folder)
"""

import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ebay_api                       # noqa: E402
import listing as lst                 # noqa: E402

CFG = {**ebay_api.CONFIG_TEMPLATE, "postal_code": "48060",
       "policies": {"shipping": "", "payment": "222", "return": "333"},
       "shipping_by_weight": {"threshold_lb": 4, "shipping_light": "LIGHT",
                              "shipping_heavy": "HEAVY"}}


def item(weight=None, **extra):
    return {**lst.LISTING_TEMPLATE, "title": "Lamp", "category_id": "1", "price": 20,
            "description_html": "<p>x</p>", "routing": {"weight_lb": weight}, **extra}


class ShippingPolicyTests(unittest.TestCase):

    def test_by_weight(self):
        self.assertEqual(lst.shipping_policy(item(3.5), CFG), "LIGHT")
        self.assertEqual(lst.shipping_policy(item(4), CFG), "LIGHT")      # 4 lb is not over 4
        self.assertEqual(lst.shipping_policy(item(4.1), CFG), "HEAVY")

    def test_per_item_override_wins(self):
        self.assertEqual(lst.shipping_policy(item(10, shipping_policy="PICKUP"), CFG), "PICKUP")

    def test_missing_weight_is_an_error(self):
        with self.assertRaises(ValueError):
            lst.shipping_policy(item(None), CFG)

    def test_default_when_not_by_weight(self):
        cfg = {**CFG, "policies": {**CFG["policies"], "shipping": "DEFAULT"},
               "shipping_by_weight": {"threshold_lb": 4, "shipping_light": "", "shipping_heavy": ""}}
        self.assertEqual(lst.shipping_policy(item(None), cfg), "DEFAULT")

    def test_xml_uses_weight_policy(self):
        xml = lst.build_item_xml("AddItem", item(9), CFG, ["https://i/1.jpg"], "U" * 32)
        root = ET.fromstring(xml)
        ns = {"e": "urn:ebay:apis:eBLBaseComponents"}
        self.assertEqual(root.find(".//e:ShippingProfileID", ns).text, "HEAVY")


if __name__ == "__main__":
    unittest.main()
