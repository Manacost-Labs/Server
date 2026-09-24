"""Real local-browser acceptance for the quality runner; no project/production targets."""

import functools
import http.server
import json
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

RUNNER = Path(__file__).resolve().parents[1] / "integrations/codex/subscription-savings/quality/browser.mjs"


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_):
        pass


class BrowserQualityTests(unittest.TestCase):
    def test_real_browser_detects_missing_baseline_and_visual_a11y_regression(self):
        self.assertTrue(shutil.which("node"), "Install Node and npm ci in quality/ before this acceptance check")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            page = root / "index.html"
            shutil.copy(RUNNER.parent / "design-system/game-asset.mjs", root / "game-asset.mjs")
            page.write_text('<!doctype html><html lang="en"><head><title>Quality test</title>'
                            '<style>button{height:40px;background:#fff;color:#111}</style></head>'
                            '<body><main><h1>Quality test</h1><button id="save">Save</button>'
                            '<div id="asset-test"></div></main><script type="module">'
                            'import {gameAsset} from "./game-asset.mjs";'
                            'const m={version:1,decorative:true,preset:"hero-art",focal_point:[.5,.5],'
                            'variants:[{file:"x.avif",format:"avif",width:20,height:10},'
                            '{file:"x.webp",format:"webp",width:20,height:10}]};'
                            'const picture=gameAsset(m,"/assets/");'
                            'if(picture.querySelectorAll("source").length!==2||picture.querySelector("img").alt!=="")throw Error("asset semantics");'
                            'let rejected=false;try{gameAsset(m,"https://invalid.example/")}catch{rejected=true}'
                            'if(!rejected)throw Error("unsafe asset URL");'
                            'document.querySelector("#asset-test").textContent="Asset component verified";'
                            'document.querySelector("#asset-test").dataset.ready="true";'
                            '</script></body></html>')
            config = {"version": 1, "widths": [375, 768], "pages": [{"id": "test", "path": "/", "ready": "#asset-test[data-ready=true]",
                      "computed": [{"selector": "#save", "property": "height", "equals": "40px"},
                                   {"selector": "#asset-test", "property": "display", "equals": "block"}],
                      "keyboardOrder": ["#save"]}]}
            (root / "browser.json").write_text(json.dumps(config))
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(QuietHandler, directory=directory))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            argv = ["node", str(RUNNER), "--project", directory, "--config", "browser.json",
                    "--base-url", f"http://127.0.0.1:{server.server_port}"]
            environment = dict(os.environ)
            if shutil.which("chromium"):
                environment["QUALITY_CHROMIUM_EXECUTABLE"] = shutil.which("chromium")

            def run(extra=()):
                process = subprocess.run(argv + list(extra), capture_output=True, text=True, timeout=90, env=environment)
                self.assertIn(process.returncode, (0, 1), process.stderr[-2000:])
                self.assertTrue(process.stdout.strip(), process.stderr[-2000:])
                return process.returncode, json.loads(process.stdout)

            try:
                code, missing = run()
                self.assertEqual(1, code)
                self.assertTrue(any(f["check"] == "missing-baseline" for f in missing["failures"]))
                code, created = run(["--update-baselines"])
                self.assertEqual(0, code, created["failures"])
                code, stable = run()
                self.assertEqual(0, code, stable["failures"])
                self.assertTrue(all(m["changedPixelRatio"] == 0 for m in stable["measurements"]))
                page.write_text(page.read_text().replace("height:40px", "height:80px").replace('>Save</button>', '></button>'))
                code, broken = run()
                self.assertEqual(1, code)
                checks = {f["check"] for f in broken["failures"]}
                self.assertTrue({"computed-style", "accessibility", "visual-regression"} <= checks, checks)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
