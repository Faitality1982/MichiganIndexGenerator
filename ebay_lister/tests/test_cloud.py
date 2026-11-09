"""
Offline tests: config from environment variables, `cloud-env`, and `add`.

    python -m unittest discover -s tests      (from the ebay_lister folder)
"""

import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ebay_api                       # noqa: E402
import ebay_lister                    # noqa: E402

ENV = {"EBAY_CLIENT_ID": "app", "EBAY_CLIENT_SECRET": "secret", "EBAY_RUNAME": "ru",
       "EBAY_REFRESH_TOKEN": "refresh", "EBAY_POSTAL_CODE": "48060",
       "EBAY_LOCATION": "Port Huron, MI", "EBAY_SHIPPING_POLICY": "1",
       "EBAY_PAYMENT_POLICY": "2", "EBAY_RETURN_POLICY": "3"}


def run_cli(*argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = ebay_lister.main(list(argv))
    return code, buf.getvalue()


class EnvConfigTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        home = Path(self.tmp.name) / "home"
        for p in (mock.patch.object(ebay_api, "HOME", home),
                  mock.patch.object(ebay_api, "CONFIG_PATH", home / "config.json"),
                  mock.patch.object(ebay_api, "TOKEN_PATH", home / "token.json")):
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def test_env_only_config(self):
        with mock.patch.dict(os.environ, ENV, clear=False):
            cfg = ebay_api.load_config()
        self.assertEqual((cfg["client_id"], cfg["postal_code"], cfg["location"]),
                         ("app", "48060", "Port Huron, MI"))
        self.assertEqual(cfg["policies"], {"shipping": "1", "payment": "2", "return": "3"})
        self.assertEqual(cfg["environment"], "production")

    def test_no_config_no_env_still_errors(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ebay_api.EbayError):
                ebay_api.load_config()

    def test_cloud_env_prints_everything(self):
        with mock.patch.dict(os.environ, ENV, clear=False):
            code, text = run_cli("cloud-env")
        self.assertEqual(code, 0)
        for key, value in ENV.items():
            self.assertIn(f"{key}={value}", text)

    def test_cloud_env_needs_sign_in(self):
        env = {k: v for k, v in ENV.items() if k != "EBAY_REFRESH_TOKEN"}
        with mock.patch.dict(os.environ, env, clear=True):
            code, text = run_cli("cloud-env")
        self.assertEqual(code, 1)
        self.assertIn("auth", text)


class AddPhotosTests(unittest.TestCase):

    def test_add_names_files_by_type(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            Image.new("RGB", (900, 600)).save(d / "upload1", "JPEG")   # no extension
            Image.new("RGB", (900, 600)).save(d / "upload2", "PNG")
            (d / "notes").write_text("not a photo")
            item = d / "listings" / "lamp"
            code, text = run_cli("add", str(item), str(d / "upload1"), str(d / "upload2"),
                                 str(d / "notes"))
            self.assertEqual(code, 0)
            self.assertEqual(sorted(p.name for p in item.iterdir()),
                             ["photo_01.jpg", "photo_02.png"])
            self.assertIn("Skipped", text)
            run_cli("add", str(item), str(d / "upload1"))
            self.assertTrue((item / "photo_03.jpg").exists())


if __name__ == "__main__":
    unittest.main()
