import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / '.agents/skills/adaptive-tutor/scripts/progress.py'

class WorkspaceResolutionTests(unittest.TestCase):
    def run_cli(self, cwd, env=None, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=cwd,
                              env=env, text=True, capture_output=True)

    def test_cwd_is_workspace_not_script_location(self):
        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td) / 'workspace'
            workspace.mkdir()
            result = self.run_cli(workspace, None, 'topic', '--id', 'intro', '--name', 'Intro')
            self.assertEqual(result.returncode, 0, result.stderr)
            dbfile = workspace / '.learning/progress.db'
            self.assertTrue(dbfile.exists())
            with sqlite3.connect(dbfile) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM topics').fetchone()[0], 1)

    def test_override_independent_of_cwd_and_script(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first, second, home = (root / x for x in ('first', 'second', 'chosen-home'))
            first.mkdir(); second.mkdir()
            env = {**os.environ, 'ADAPTIVE_TUTOR_HOME': str(home)}
            result = self.run_cli(first, env, 'topic', '--id', 'saved', '--name', 'Saved')
            self.assertEqual(result.returncode, 0, result.stderr)
            result = self.run_cli(second, env, 'status')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('saved', result.stdout)
            self.assertTrue((home / '.learning/progress.db').is_file())
            self.assertFalse((first / '.learning/progress.db').exists())
            self.assertFalse((second / '.learning/progress.db').exists())

    def test_separate_workspaces_are_isolated(self):
        with tempfile.TemporaryDirectory() as td:
            a, b = Path(td)/'a', Path(td)/'b'
            a.mkdir(); b.mkdir()
            env = {k:v for k,v in os.environ.items() if k != 'ADAPTIVE_TUTOR_HOME'}
            self.assertEqual(self.run_cli(a, env, 'topic', '--id', 'only-a', '--name', 'A').returncode, 0)
            result = self.run_cli(b, env, 'status')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn('only-a', result.stdout)

    def test_empty_override_is_error(self):
        with tempfile.TemporaryDirectory() as td:
            env = {**os.environ, 'ADAPTIVE_TUTOR_HOME': '  '}
            result = self.run_cli(Path(td), env, 'status')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('ADAPTIVE_TUTOR_HOME', result.stderr)

if __name__ == '__main__':
    unittest.main()
