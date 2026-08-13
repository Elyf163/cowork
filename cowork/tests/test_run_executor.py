import argparse
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


RUNNER = Path(__file__).parents[1] / "scripts/run_executor.py"
SPEC = importlib.util.spec_from_file_location("run_executor", RUNNER)
assert SPEC and SPEC.loader
run_executor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(run_executor)


class CommandTest(unittest.TestCase):
    def args(self, **overrides):
        values = {
            "bwrap_bin": None,
            "executor": "opencode",
            "max_steps": 12,
            "model": None,
            "network": True,
            "opencode_bin": None,
            "reasonix_bin": None,
        }
        values.update(overrides)
        return argparse.Namespace(**values)

    @patch.object(run_executor, "executable", side_effect=lambda name, _: f"/bin/{name}")
    def test_opencode_inherits_model_unless_explicitly_overridden(self, _):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            default = run_executor.executor_command(self.args(), project, "do it")
            explicit = run_executor.executor_command(
                self.args(model="provider/model"), project, "do it"
            )

        self.assertNotIn("--model", default)
        self.assertEqual(explicit[-3:], ["--model", "provider/model", "do it"])
        self.assertIn("/tmp/cowork-real-git", default)

    @patch.object(run_executor, "executable", side_effect=lambda name, _: f"/bin/{name}")
    def test_reasonix_backend_remains_available(self, _):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            reasonix_home = project / "reasonix-home"
            reasonix_home.mkdir()
            with patch.dict("os.environ", {"REASONIX_HOME": str(reasonix_home)}):
                command = run_executor.executor_command(
                    self.args(executor="reasonix"), project, "do it"
                )

        self.assertIn("/bin/reasonix", command)
        self.assertIn("--max-steps", command)


if __name__ == "__main__":
    unittest.main()
