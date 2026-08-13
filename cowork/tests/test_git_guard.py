from pathlib import Path
import unittest


SOURCE = (Path(__file__).parents[1] / "scripts/git_guard.py").read_text()
FUNCTIONS = SOURCE.split("command = subcommand", 1)[0]
namespace = {"__name__": "git_guard_test"}
exec(compile(FUNCTIONS, "git_guard.py", "exec"), namespace)
subcommand = namespace["subcommand"]


class GitGuardTest(unittest.TestCase):
    def test_finds_subcommand_after_global_options(self):
        self.assertEqual(subcommand(["-C", "/project", "status", "--short"]), "status")
        self.assertEqual(subcommand(["--no-pager", "diff"]), "diff")

    def test_state_changing_subcommand_is_not_allowlisted(self):
        for command in ("commit", "push", "merge", "reset", "clean", "checkout", "worktree"):
            self.assertNotIn(command, namespace["ALLOWED"])


if __name__ == "__main__":
    unittest.main()
