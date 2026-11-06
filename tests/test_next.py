import importlib.util
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / '.agents/skills/adaptive-tutor/scripts/progress.py'
spec = importlib.util.spec_from_file_location('tutor_progress', SCRIPT)
progress = importlib.util.module_from_spec(spec)
spec.loader.exec_module(progress)


class NextTopicTests(unittest.TestCase):
    def test_prerequisites_and_status_transitions(self):
        with tempfile.TemporaryDirectory() as d:
            old = progress.DB_PATH
            progress.DB_PATH = Path(d) / 'progress.db'
            try:
                with progress.connect() as db:
                    db.executemany('INSERT INTO topics(id,name) VALUES(?,?)', [
                        ('basic', 'Basics'), ('middle', 'Middle'), ('advanced', 'Advanced'),
                        ('separate', 'Separate')])
                    db.executemany('INSERT INTO edges(before_id,after_id) VALUES(?,?)', [
                        ('basic','middle'), ('middle','advanced')])
                    result=progress.next_topics(db)
                    self.assertEqual(result['recommended']['id'], 'basic')
                    self.assertEqual({x['id'] for x in result['blocked']}, {'middle','advanced'})
                    db.execute('INSERT INTO attempts(topic_id,question,answer,evaluation,difficulty) VALUES(?,?,?,?,?)',
                               ('basic','q1','a1','correct',3))
                    self.assertEqual(progress.topic_states(db)['basic']['status'], 'emerging')
                    db.execute('INSERT INTO attempts(topic_id,question,answer,evaluation,difficulty) VALUES(?,?,?,?,?)',
                               ('basic','q2','a2','correct',3))
                    db.execute("UPDATE attempts SET question_type='practice' WHERE topic_id='basic' AND question='q1'")
                    db.execute("UPDATE attempts SET question_type='transfer' WHERE topic_id='basic' AND question='q2'")
                    self.assertEqual(progress.topic_states(db)['basic']['status'], 'demonstrated')
                    self.assertEqual(progress.next_topics(db)['recommended']['id'], 'middle')
                    db.execute('INSERT INTO attempts(topic_id,question,answer,evaluation,difficulty) VALUES(?,?,?,?,?)',
                               ('middle','q1','a','partial',2))
                    self.assertEqual(progress.topic_states(db)['middle']['status'], 'emerging')
                    db.execute('INSERT INTO attempts(topic_id,question,answer,evaluation,difficulty) VALUES(?,?,?,?,?)',
                               ('middle','q2','a','incorrect',2))
                    self.assertEqual(progress.topic_states(db)['middle']['status'], 'developing')
                    self.assertEqual(progress.next_topics(db)['recommended']['id'], 'middle')
                    self.assertIn('middle', next(x for x in progress.next_topics(db)['blocked'] if x['id']=='advanced')['unmet_prerequisites'])
                    # Distinct question text required for demonstration.
                    db.execute('INSERT INTO attempts(topic_id,question,answer,evaluation,difficulty) VALUES(?,?,?,?,?)',
                               ('middle','new','a','correct',3))
                    db.execute('INSERT INTO attempts(topic_id,question,answer,evaluation,difficulty) VALUES(?,?,?,?,?)',
                               ('middle','new','a','correct',3))
                    self.assertNotEqual(progress.topic_states(db)['middle']['status'], 'demonstrated')
                    db.execute('INSERT INTO attempts(topic_id,question,answer,evaluation,difficulty) VALUES(?,?,?,?,?)',
                               ('middle','new2','a','correct',3))
                    db.execute("UPDATE attempts SET question_type='practice' WHERE topic_id='middle' AND question='new'")
                    db.execute("UPDATE attempts SET question_type='transfer' WHERE topic_id='middle' AND question='new2'")
                    self.assertEqual(progress.next_topics(db)['recommended']['id'], 'advanced')
            finally:
                progress.DB_PATH = old

    def test_empty_graph(self):
        with tempfile.TemporaryDirectory() as d:
            old = progress.DB_PATH
            progress.DB_PATH = Path(d) / 'progress.db'
            try:
                with progress.connect() as db:
                    self.assertIsNone(progress.next_topics(db)['recommended'])
            finally:
                progress.DB_PATH = old

if __name__ == '__main__':
    unittest.main()
