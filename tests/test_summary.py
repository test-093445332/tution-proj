import importlib.util
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / '.agents/skills/adaptive-tutor/scripts/progress.py'
spec = importlib.util.spec_from_file_location('tutor_progress_summary', SCRIPT)
progress = importlib.util.module_from_spec(spec)
spec.loader.exec_module(progress)


class SummaryTests(unittest.TestCase):
    def test_more_than_thirty_attempts_across_topics(self):
        with tempfile.TemporaryDirectory() as d:
            original = progress.DB_PATH
            progress.DB_PATH = Path(d) / 'state.db'
            try:
                with progress.connect() as db:
                    db.executemany('INSERT INTO topics(id,name) VALUES (?,?)',
                                   [('old','Old concept'),('new','New concept'),('blank','Blank concept')])
                    # Old concept is still present even though 45 newer records follow.
                    db.execute('''INSERT INTO attempts(topic_id,question,answer,evaluation,evidence,difficulty,created_at)
                                  VALUES (?,?,?,?,?,?,?)''',
                               ('old','old_question','old_answer','incorrect','Old misconception',2,'2025-01-01 00:00:00'))
                    for n in range(45):
                        db.execute('''INSERT INTO attempts(topic_id,question,answer,evaluation,evidence,difficulty,created_at)
                                      VALUES (?,?,?,?,?,?,?)''',
                                   ('new',f'q{n}','a','incorrect' if n % 2 else 'correct',
                                    f'error {n}' if n % 2 else '',2,f'2026-01-01 00:00:{n:02d}'))
                    data = {x['id']: x for x in progress.topic_summaries(db)}
                    self.assertEqual(len(data),3)
                    self.assertEqual(data['old']['attempt_count'],1)
                    self.assertEqual(data['old']['last_result'],'incorrect')
                    self.assertEqual(data['old']['last_checked_at'],'2025-01-01 00:00:00')
                    self.assertEqual(data['old']['recent_errors'][0]['evidence'],'Old misconception')
                    self.assertEqual(data['new']['attempt_count'],45)
                    self.assertEqual(data['new']['correct_count'],23)
                    self.assertEqual(data['new']['incorrect_count'],22)
                    self.assertEqual(data['new']['last_result'],'correct')
                    self.assertEqual([x['evidence'] for x in data['new']['recent_errors']],
                                     ['error 43','error 41','error 39'])
                    self.assertIsNone(data['blank']['last_result'])
                    self.assertIsNone(data['blank']['last_checked_at'])
                    self.assertEqual(data['blank']['attempt_count'],0)
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0],46)
            finally:
                progress.DB_PATH = original


if __name__ == '__main__':
    unittest.main()
