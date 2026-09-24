"""Release and project-client boundaries must fail before touching existing data."""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SOURCE = Path(__file__).resolve().parents[1] / "integrations/codex/subscription-savings"
sys.path.insert(0, str(SOURCE))


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


quality_release = module("quality_release", SOURCE / "quality_release.py")
client = module("project_client", SOURCE / "quality/project_client.py")
background = module("background_remove", SOURCE / "quality/background_remove.py")


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        subprocess.run(["git", "init", "-q", str(self.source)], check=True)
        (self.source / "context_economy.py").write_text("print('candidate')\n")
        subprocess.run(["git", "-C", str(self.source), "add", "."], check=True)
        # A disposable fixture commit gives the release builder real provenance.
        subprocess.run(["git", "-C", str(self.source), "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                        "commit", "-qm", "fixture"], check=True)

    def test_release_is_new_and_tampering_fails(self):
        output = self.root / "release"
        result = quality_release.prepare(self.source, output)
        self.assertFalse(result["activated"])
        self.assertTrue(quality_release.verify(output)["ok"])
        with self.assertRaises(ValueError):
            quality_release.prepare(self.source, output)
        (output / "context_economy.py").write_text("modified\n")
        self.assertEqual(quality_release.verify(output)["mismatches"], ["context_economy.py"])

    def test_credentials_and_symlinks_never_enter_release(self):
        for name in (".env", "credentials.json"):
            target = self.source / name
            target.write_text("fixture")
            with self.assertRaises(ValueError):
                quality_release.prepare(self.source, self.root / "candidate")
            self.assertFalse((self.root / "candidate").exists())
            target.unlink()
        (self.source / "linked.py").symlink_to(self.source / "context_economy.py")
        with self.assertRaises(ValueError):
            quality_release.prepare(self.source, self.root / "candidate")

    def test_background_rejects_unprovisioned_model_before_import(self):
        model = self.root / "untrusted.onnx"
        model.write_bytes(b"x" * 4574861)
        with self.assertRaisesRegex(ValueError, "checksum"):
            background.remove(self.root / "source.png", self.root / "out.png", model)
        self.assertFalse((self.root / "out.png").exists())

    def test_project_client_rejects_escaped_or_unknown_configuration(self):
        (self.source / "Makefile").write_text("test:\n\ttrue\n")
        config = {"stack": "wordpress", "checks": [{"id": "test", "argv": ["make", "test"]}]}
        path = self.source / "quality.json"
        path.write_text(json.dumps(config))
        self.assertTrue(client.validate(self.source, path.name)["ok"])
        config["checks"][0]["heavy"] = True
        path.write_text(json.dumps(config))
        with self.assertRaisesRegex(ValueError, "Unknown"):
            client.validate(self.source, path.name)
        outside = self.root / "outside.json"
        outside.write_text("{}")
        (self.source / "linked.json").symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "project-local"):
            client.validate(self.source, "linked.json")

    def test_provisioned_tokenizer_counts_without_any_network_loader(self):
        import offline_tokenizer

        directory = os.environ.get('MANACOST_TOKENIZER_CACHE')
        self.assertTrue(directory and Path(directory, 'metadata.json').is_file(),
                        'Provision the pinned offline tokenizer before canonical verification')
        offline_tokenizer.load.cache_clear()
        with mock.patch('socket.socket.connect', side_effect=AssertionError('network forbidden')), \
                mock.patch('tiktoken.get_encoding', side_effect=AssertionError('runtime loader forbidden')):
            result = offline_tokenizer.estimate('hello world')
            self.assertEqual(result['tokenizer_tokens'], 2)
            self.assertEqual(result['estimated_tokens'], 3)
            russian = offline_tokenizer.estimate('Повторно используй уже существующий код.')
            self.assertLess(russian['estimated_tokens'], len('Повторно используй уже существующий код.'.encode()))

    def test_absent_tokenizer_is_a_conservative_offline_fallback(self):
        from context_economy import packing

        with mock.patch.dict(os.environ, {'MANACOST_TOKENIZER_CACHE': str(self.root / 'absent')}), \
                mock.patch('socket.socket.connect', side_effect=AssertionError('network forbidden')):
            self.assertEqual(packing.estimate('hello'), 6)

    def test_operator_release_path_and_arguments_are_never_shell_expanded(self):
        candidate = self.root / 'candidate;touch SHELL_EXECUTED'
        (candidate / '.venv/bin').mkdir(parents=True)
        (candidate / '.venv/bin/python').symlink_to(sys.executable)
        receipt = self.root / 'argv.json'
        (candidate / 'context_economy.py').write_text(
            f'import sys,json,pathlib;pathlib.Path({str(receipt)!r}).write_text(json.dumps(sys.argv))\n')
        (self.source / 'Makefile').write_text('test:\n\ttrue\n')
        (self.source / 'quality.json').write_text(json.dumps({'stack': 'wordpress', 'checks': [{'id': 'test', 'argv': ['make', 'test']}]}))
        changed = 'path;touch SHELL_EXECUTED'
        with mock.patch.dict(os.environ, {'MANACOST_QUALITY_ROOT': str(candidate)}), \
                mock.patch.object(sys, 'argv', ['quality-guard', '--config', 'quality.json', '--plan', '--changed', changed]):
            self.assertEqual(client.main(self.source), 0)
        self.assertEqual(json.loads(receipt.read_text())[-1], changed)
        self.assertFalse((self.source / 'SHELL_EXECUTED').exists())

    def test_default_family_plan_and_verify_use_the_real_cli(self):
        candidate = self.root / 'actual-cli'
        (candidate / '.venv/bin').mkdir(parents=True)
        (candidate / '.venv/bin/python').symlink_to(sys.executable)
        (candidate / 'context_economy.py').write_text(
            f'import sys,runpy;sys.path.insert(0,{str(SOURCE)!r});'
            f'sys.argv[1:1]=["--state-dir",{str(self.root / "state")!r}];'
            f'runpy.run_path({str(SOURCE / "context_economy.py")!r},run_name="__main__")\n')
        (self.source / 'quality.json').write_text(json.dumps({'version': 1, 'stack': 'wordpress', 'checks': [
            {'id': 'local-smoke', 'argv': [sys.executable, '-c', 'print("local smoke passed")']}]}))
        for mode in (['--plan'], []):
            with mock.patch.dict(os.environ, {'MANACOST_QUALITY_ROOT': str(candidate)}), \
                    mock.patch.object(sys, 'argv', ['quality-guard', '--config', 'quality.json', *mode]):
                self.assertEqual(client.main(self.source), 0)


if __name__ == "__main__":
    unittest.main()
