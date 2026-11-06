import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / '.agents/skills/adaptive-tutor/scripts/progress.py'

class PortabilityTests(unittest.TestCase):
    def test_file_input_utf8_and_utf8_bom(self):
        for encoding in ('utf-8', 'utf-8-sig'):
            with self.subTest(encoding=encoding), tempfile.TemporaryDirectory() as directory:
                wd = Path(directory)
                payload = {'topic': 'ip', 'question': 'What is IP?',
                           'answer': 'Строка с "кавычками", $PATH, `echo x`, $(whoami)\nвторая строка',
                           'evaluation': 'partial', 'evidence': 'Проверка юникода', 'difficulty': 2}
                def run(*arguments):
                    return subprocess.run([sys.executable, str(SCRIPT), *arguments],
                                          cwd=wd, capture_output=True, text=True)
                self.assertEqual(run('topic', '--id', 'ip', '--name', 'IP').returncode, 0)
                file = wd / 'attempt.json'
                file.write_text(json.dumps(payload, ensure_ascii=False), encoding=encoding)
                result = run('attempt', '--json-file', str(file))
                self.assertEqual(result.returncode, 0, result.stderr)
                import sqlite3
                with sqlite3.connect(wd / '.learning/progress.db') as db:
                    saved = db.execute('SELECT answer,evidence FROM attempts').fetchone()
                self.assertEqual(saved, (payload['answer'], payload['evidence']))

    def test_missing_file_reports_cli_error(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, str(SCRIPT), 'attempt', '--json-file', 'missing.json'],
                                    cwd=directory, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Cannot read UTF-8 attempt JSON file', result.stderr)
            self.assertNotIn('Traceback', result.stderr)

if __name__ == '__main__':
    unittest.main()
