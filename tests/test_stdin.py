import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / '.agents/skills/adaptive-tutor/scripts/progress.py'
spec = importlib.util.spec_from_file_location('tutor_progress_stdin', SCRIPT)
progress = importlib.util.module_from_spec(spec)
spec.loader.exec_module(progress)


class StdinTests(unittest.TestCase):
    def test_json_exact_roundtrip_without_shell_interpolation(self):
        answer = 'First line with "quotes", $HOME, `touch /tmp/pwned`, $(whoami), \\ and newline\nВторая строка: {json} & | ;'
        payload = {'topic': 'ip', 'question': 'Explain "IP"\nwith examples',
                   'answer': answer, 'evaluation': 'partial',
                   'evidence': 'Mentions "$PATH", but not routing\nNext line', 'difficulty': 3}
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            copy = root / 'work/.agents/skills/adaptive-tutor/scripts/progress.py'
            copy.parent.mkdir(parents=True)
            copy.write_bytes(SCRIPT.read_bytes())
            result = subprocess.run([sys.executable, str(copy), 'topic', '--id', 'ip', '--name', 'IP'],
                                    capture_output=True, text=True, cwd=copy.parents[4])
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([sys.executable, str(copy), 'attempt'],
                                    input=json.dumps(payload, ensure_ascii=False),
                                    capture_output=True, text=True, cwd=copy.parents[4])
            self.assertEqual(result.returncode, 0, result.stderr)
            import sqlite3
            with sqlite3.connect(root / 'work/.learning/progress.db') as db:
                row = db.execute('SELECT question,answer,evidence,difficulty FROM attempts').fetchone()
            self.assertEqual(row, (payload['question'], answer, payload['evidence'], 3))

    def test_bad_json_and_types(self):
        cases = ['{bad', '[]', json.dumps({'topic': 'x'}), json.dumps({
            'topic':'x','question':'q','answer':'a','evaluation':'correct','evidence':'e','difficulty': True})]
        for body in cases:
            with self.subTest(body=body):
                with self.assertRaises(ValueError):
                    progress.read_attempt_from_stdin(io.StringIO(body))

    def test_old_answer_arguments_are_not_accepted(self):
        result = subprocess.run([sys.executable, str(SCRIPT), 'attempt', '--answer', 'abc'],
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('unrecognized arguments', result.stderr)

if __name__ == '__main__':
    unittest.main()
