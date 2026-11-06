import importlib.util
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / '.agents/skills/adaptive-tutor/scripts/progress.py'
spec = importlib.util.spec_from_file_location('tutor_progress_v2', SCRIPT)
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)

class V2Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.old=p.DB_PATH
        p.DB_PATH=Path(self.tmp.name)/'.learning'/'progress.db'
        self.db=p.connect()
    def tearDown(self):
        self.db.close()
        p.DB_PATH=self.old
        self.tmp.cleanup()
    def cli(self,*args,stdin=None):
        env={**os.environ,'ADAPTIVE_TUTOR_HOME':self.tmp.name}
        return subprocess.run([sys.executable,str(SCRIPT),*args],input=stdin,text=True,capture_output=True,env=env,cwd=self.tmp.name)
    def test_new_schema_and_goal_session(self):
        self.assertEqual(self.db.execute('PRAGMA user_version').fetchone()[0],2)
        self.assertEqual(self.cli('subject','--id','os','--name','Operating Systems').returncode,0)
        result=self.cli('goal','--subject','os','--objective','Understand virtual memory','--depth','advanced','--language','ru','--minutes','30')
        self.assertEqual(result.returncode,0,result.stderr)
        gid=json.loads(result.stdout)['goal_id']
        result=self.cli('session','--subject','os','--goal-id',str(gid))
        self.assertEqual(result.returncode,0,result.stderr)
        sid=json.loads(result.stdout)['session_id']
        self.assertEqual(self.cli('end-session','--id',str(sid),'--summary','Done').returncode,0)
        data=json.loads(self.cli('status','--subject','os').stdout)
        self.assertEqual(data['goals'][0]['language'],'ru')
        self.assertEqual(data['sessions'][0]['summary'],'Done')
    def test_errors_are_clean(self):
        for args,msg in [
            (('edge','--before','missing','--after','other'),'not found'),
            (('topic','--id','x','--name','X','--subject','missing'),'not found'),
            (('void','--id','999','--reason','wrong'),'not found'),
        ]:
            res=self.cli(*args)
            self.assertEqual(res.returncode,2)
            self.assertNotIn('Traceback',res.stderr)
            self.assertIn(msg,res.stderr)
            self.assertFalse(json.loads(res.stderr)['ok'])
    def test_evidence_and_stdin(self):
        self.db.execute("INSERT INTO topics(id,name) VALUES('a','A')")
        self.db.commit()
        base={'topic':'a','question':'Explain X','answer':'`$(bad)`\nПривет',
              'evaluation':'correct','evidence':'Independent derivation','difficulty':4,
              'question_type':'practice','hint_used':False}
        result=self.cli('attempt',stdin=json.dumps(base,ensure_ascii=False))
        self.assertEqual(result.returncode,0,result.stderr)
        self.db.execute('SELECT 1')
        self.assertEqual(self.db.execute("SELECT answer FROM attempts").fetchone()[0],base['answer'])
        for key,value in [('answer',''),('evidence',''),('question_type','unknown'),('hint_used',1)]:
            bad=dict(base);bad[key]=value
            res=self.cli('attempt',stdin=json.dumps(bad))
            self.assertEqual(res.returncode,2)
            self.assertNotIn('Traceback',res.stderr)
    def test_demonstrated_requires_independent_transfer(self):
        self.db.execute("INSERT INTO topics(id,name) VALUES('a','A')")
        self.db.executemany('''INSERT INTO attempts(topic_id,question,answer,evaluation,evidence,difficulty,question_type,hint_used)
                              VALUES('a',?, 'a','correct','good',4,?,?)''',[
                              ('q1','practice',0),('q2','diagnostic',0)])
        self.assertEqual(p.topic_states(self.db)['a']['status'],'developing')
        self.db.execute("INSERT INTO attempts(topic_id,question,answer,evaluation,evidence,difficulty,question_type,hint_used) VALUES('a','q3','a','correct','good',4,'transfer',1)")
        self.assertEqual(p.topic_states(self.db)['a']['status'],'developing')
        self.db.execute("INSERT INTO attempts(topic_id,question,answer,evaluation,evidence,difficulty,question_type,hint_used) VALUES('a','q4','a','correct','good',4,'transfer',0)")
        self.assertEqual(p.topic_states(self.db)['a']['status'],'demonstrated')
    def test_review_due_and_subject_isolation(self):
        self.db.execute("INSERT INTO subjects(id,name) VALUES('math','Math')")
        self.db.execute("INSERT INTO topics(id,name,subject_id) VALUES('m','M','math')")
        self.db.execute("INSERT INTO topics(id,name) VALUES('a','A')")
        self.db.execute("INSERT INTO attempts(topic_id,question,answer,evaluation,evidence,created_at) VALUES('m','q','a','incorrect','wrong','2020-01-01 00:00:00')")
        self.db.execute("INSERT INTO attempts(topic_id,question,answer,evaluation,evidence,created_at) VALUES('a','q','a','correct','good','2020-01-01 00:00:00')")
        self.assertEqual([x['id'] for x in p.due_reviews(self.db,'math')],['m'])
        self.assertEqual([x['id'] for x in p.topic_summaries(self.db,subject='math')],['m'])
        self.assertEqual([x['id'] for x in p.next_topics(self.db,'math')['ready']],['m'])
    def test_amend_void_audit(self):
        self.db.execute("INSERT INTO topics(id,name) VALUES('a','A')")
        self.db.commit()
        a={'topic':'a','question':'Q','answer':'A','evaluation':'incorrect','evidence':'failed','difficulty':3,'question_type':'practice','hint_used':False}
        r=self.cli('attempt',stdin=json.dumps(a));self.assertEqual(r.returncode,0,r.stderr)
        id1=json.loads(r.stdout)['attempt_id']
        a['evaluation']='correct';a['evidence']='Verified correction'
        fn=Path(self.tmp.name)/'amend.json';fn.write_text(json.dumps(a),encoding='utf-8')
        r=self.cli('amend','--id',str(id1),'--json-file',str(fn))
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(p.topic_summaries(self.db)[0]['attempt_count'],1)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0],2)
        id2=json.loads(r.stdout)['replacement_attempt']
        self.assertEqual(self.cli('void','--id',str(id2),'--reason','Bad grade').returncode,0)
        self.assertEqual(p.topic_summaries(self.db)[0]['attempt_count'],0)
    def test_legacy_migration(self):
        self.db.close()
        path=p.DB_PATH
        path.unlink()
        with sqlite3.connect(path) as d:
            d.executescript('''CREATE TABLE topics(id TEXT PRIMARY KEY,name TEXT NOT NULL,description TEXT NOT NULL DEFAULT '',created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE edges(before_id TEXT, after_id TEXT,PRIMARY KEY(before_id,after_id));
            CREATE TABLE attempts(id INTEGER PRIMARY KEY, topic_id TEXT NOT NULL,question TEXT NOT NULL, answer TEXT NOT NULL,evaluation TEXT NOT NULL,evidence TEXT NOT NULL DEFAULT '',difficulty INTEGER NOT NULL DEFAULT 2,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            INSERT INTO topics(id,name) VALUES('old','Old');
            INSERT INTO attempts(topic_id,question,answer,evaluation,evidence) VALUES('old','Q','A','correct','legacy evidence');''')
        self.db=p.connect()
        self.assertEqual(p.topic_summaries(self.db)[0]['attempt_count'],1)
        self.assertEqual(p.topic_states(self.db)['old']['status'],'emerging')
        self.assertEqual(self.db.execute('PRAGMA user_version').fetchone()[0],2)
        self.assertEqual(self.db.execute("SELECT question_type FROM attempts").fetchone()[0],'diagnostic')
    def test_cross_subject_edge_and_session(self):
        self.db.execute("INSERT INTO subjects(id,name) VALUES('other','Other')")
        self.db.execute("INSERT INTO topics(id,name) VALUES('a','A')")
        self.db.execute("INSERT INTO topics(id,name,subject_id) VALUES('b','B','other')")
        self.db.commit()
        res=self.cli('edge','--before','a','--after','b')
        self.assertEqual(res.returncode,2)
        self.assertIn('different subjects',res.stderr)

if __name__=='__main__':unittest.main()
