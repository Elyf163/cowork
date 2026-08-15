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
        values = {"bwrap_bin": None, "network": True, "unsafe_fallback": False,
                  "max_steps": 12}
        values.update(overrides)
        return argparse.Namespace(**values)

    def test_opencode_inherits_model_unless_explicitly_overridden(self):
        project = Path("/project")
        envelope = run_executor.task_envelope(project, 1, {
            "id": "t1", "agent": "opencode", "allowed_paths": ["src"],
            "objective": "do it", "checks": [],
        }, "sha256:abc")
        default, default_input = run_executor.render_agent_command(
            run_executor.load_agents(project)["opencode"], project, envelope
        )
        explicit, _ = run_executor.render_agent_command(
            run_executor.load_agents(project)["opencode"], project, envelope,
            "provider/model"
        )

        self.assertNotIn("--model", default)
        self.assertIsNone(default_input)
        self.assertIn("--model", explicit)
        self.assertIn("provider/model", explicit)

    def test_reasonix_receives_the_compact_envelope_on_stdin(self):
        project = Path("/project")
        envelope = run_executor.task_envelope(project, 1, {
            "id": "t1", "agent": "reasonix", "allowed_paths": ["src"],
            "objective": "do it", "checks": [],
        }, "sha256:abc")
        command, input_text = run_executor.render_agent_command(
            run_executor.load_agents(project)["reasonix"], project, envelope
        )

        self.assertIn("reasonix", command[0])
        self.assertEqual(input_text, envelope)
        self.assertNotIn("--model", command)

    @patch.object(run_executor, "executable", side_effect=lambda name, _: f"/bin/{name}")
    def test_linux_command_keeps_git_guard_mount(self, _):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / ".cowork").mkdir()
            command = run_executor.linux_sandbox(
                ["/bin/true"], project, self.args(), run_executor.load_agents(project)["opencode"]
            )
        if command is not None:
            self.assertIn("/tmp/cowork-real-git", command)


if __name__ == "__main__":
    unittest.main()
