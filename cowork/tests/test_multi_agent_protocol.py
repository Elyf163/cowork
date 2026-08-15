import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from importlib.util import module_from_spec, spec_from_file_location


RUNNER = Path(__file__).parents[1] / "scripts/run_executor.py"
SPEC = spec_from_file_location("run_executor_protocol", RUNNER)
assert SPEC and SPEC.loader
runner = module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


class MultiAgentProtocolTest(unittest.TestCase):
    def test_registry_merges_configured_agents_without_shell(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            cowork = project / ".cowork"
            cowork.mkdir()
            (cowork / "executors.json").write_text(json.dumps({
                "agents": {
                    "claude-code": {"command": ["claude", "-p", "{prompt}"]},
                    "custom": {"command": ["agent", "--root", "{root}"]},
                }
            }))
            agents = runner.load_agents(project)

        self.assertIn("claude-code", agents)
        self.assertEqual(agents["custom"]["command"][-1], "{root}")
        self.assertIsInstance(agents["custom"]["command"], list)

    def test_envelope_is_short_and_reasonix_receives_it(self):
        task = {
            "id": "t1",
            "agent": "reasonix",
            "objective": "fix parser",
            "allowed_paths": ["src/parser.py"],
            "checks": ["python -m unittest"],
        }
        envelope = runner.task_envelope(Path("/repo"), 1, task, "sha256:abc")
        self.assertLess(len(envelope), 600)
        self.assertIn(".cowork/round-01-tasks.jsonl", envelope)
        command, input_text = runner.render_agent_command(
            runner.load_agents(Path("/repo"))["reasonix"], Path("/repo"), envelope
        )
        self.assertEqual(input_text, envelope)
        self.assertNotIn("--model", command)

    def test_invalid_path_and_unknown_agent_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / ".cowork").mkdir()
            with self.assertRaises(ValueError):
                runner.validate_task(project, {"id": "bad", "agent": "missing", "allowed_paths": ["../x"]}, {})

    def test_unverified_platform_does_not_run_reasonix(self):
        args = type("Args", (), {"unsafe_fallback": False, "network": True})()
        with patch.object(runner, "linux_sandbox", return_value=None):
            with self.assertRaises(ValueError):
                runner.command_for_platform(["reasonix"], Path("/project"), args,
                                            runner.load_agents(Path("/project"))["reasonix"])


if __name__ == "__main__":
    unittest.main()
