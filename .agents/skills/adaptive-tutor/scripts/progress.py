#!/usr/bin/env python3
"""Adaptive Tutor local study-state CLI. Standard library only; JSON input for user text."""
import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

VERSION = 2
KINDS = ('diagnostic', 'practice', 'transfer', 'retrieval')
EVALS = ('correct', 'partial', 'incorrect', 'uncertain')
STATUSES = ('unassessed', 'emerging', 'developing', 'demonstrated')

class TutorError(ValueError):
    pass


def resolve_data_root():
    configured = os.environ.get('ADAPTIVE_TUTOR_HOME')
    if configured is not None:
        if not configured.strip():
            raise TutorError('ADAPTIVE_TUTOR_HOME must name a non-empty directory')
        return Path(configured).expanduser().resolve()
    return Path.cwd().resolve()


try:
    DB_PATH = resolve_data_root() / '.learning' / 'progress.db'
except TutorError:
    # Defer configuration errors to CLI handling; avoid a Python traceback at import.
    DB_PATH = None


def column_exists(db, table, column):
    return any(row[1] == column for row in db.execute(f'PRAGMA table_info({table})'))


def migrate(db):
    """Non-destructive migrations from legacy v1; preserve historical assessments."""
    db.execute('PRAGMA foreign_keys=ON')
    version = db.execute('PRAGMA user_version').fetchone()[0]
    if version > VERSION:
        raise TutorError(f'Database schema v{version} is newer than supported v{VERSION}; upgrade the skill')
    with db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS subjects (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS goals (
          id INTEGER PRIMARY KEY AUTOINCREMENT, subject_id TEXT NOT NULL REFERENCES subjects(id),
          objective TEXT NOT NULL, depth TEXT NOT NULL DEFAULT 'intermediate',
          language TEXT NOT NULL DEFAULT 'auto', minutes_per_session INTEGER,
          constraints_text TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS sessions (
          id INTEGER PRIMARY KEY AUTOINCREMENT, subject_id TEXT NOT NULL REFERENCES subjects(id),
          goal_id INTEGER REFERENCES goals(id), started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          ended_at TEXT, summary TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS topics (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS edges (
          before_id TEXT NOT NULL REFERENCES topics(id),
          after_id TEXT NOT NULL REFERENCES topics(id),
          PRIMARY KEY(before_id,after_id), CHECK(before_id!=after_id)
        );
        CREATE TABLE IF NOT EXISTS attempts (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          topic_id TEXT NOT NULL REFERENCES topics(id),
          question TEXT NOT NULL, answer TEXT NOT NULL,
          evaluation TEXT NOT NULL CHECK(evaluation IN ('correct','partial','incorrect','uncertain')),
          evidence TEXT NOT NULL DEFAULT '',
          difficulty INTEGER NOT NULL DEFAULT 2 CHECK(difficulty BETWEEN 1 AND 5),
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        ''')
        db.execute("INSERT OR IGNORE INTO subjects(id,name) VALUES('default','General study')")
        for table, col, definition in [
          ('topics','subject_id',"TEXT NOT NULL DEFAULT 'default'"),
          ('attempts','session_id','INTEGER REFERENCES sessions(id)'),
          ('attempts','question_type',"TEXT NOT NULL DEFAULT 'diagnostic'"),
          ('attempts','hint_used','INTEGER NOT NULL DEFAULT 0'),
          ('attempts','voided','INTEGER NOT NULL DEFAULT 0'),
          ('attempts','source_note','TEXT NOT NULL DEFAULT \'\''),
        ]:
            if not column_exists(db, table, col):
                db.execute(f'ALTER TABLE {table} ADD COLUMN {col} {definition}')
        db.execute('CREATE INDEX IF NOT EXISTS idx_topic_subject ON topics(subject_id)')
        db.execute('CREATE INDEX IF NOT EXISTS idx_attempt_topic ON attempts(topic_id,id)')
        db.execute('CREATE INDEX IF NOT EXISTS idx_session_subject ON sessions(subject_id)')
        db.execute(f'PRAGMA user_version={VERSION}')


def connect():
    if DB_PATH is None:
        resolve_data_root()  # raises a clean configuration error
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.execute('PRAGMA foreign_keys=ON')
    try:
        migrate(db)
    except Exception:
        db.close()
        raise
    return db


def exists(db, table, identifier):
    return db.execute(f'SELECT 1 FROM {table} WHERE id=?', (identifier,)).fetchone() is not None


def require(db, table, identifier):
    if not exists(db, table, identifier):
        label = {'topics':'Topic', 'subjects':'Subject', 'sessions':'Session', 'goals':'Goal'}[table]
        raise TutorError(f'{label} "{identifier}" not found. Create it first.')


def has_path(db, source, target):
    seen = set()
    queue = [source]
    while queue:
        cur = queue.pop()
        if cur == target:
            return True
        if cur in seen:
            continue
        seen.add(cur)
        queue.extend(row[0] for row in db.execute('SELECT after_id FROM edges WHERE before_id=?',(cur,)))
    return False


def recent_evidence(db, subject=None):
    sql = '''SELECT t.id,t.name,t.subject_id,a.id,a.question,a.evaluation,a.difficulty,
                    a.question_type,a.hint_used,a.created_at
             FROM topics t LEFT JOIN attempts a ON a.topic_id=t.id AND a.voided=0'''
    params = []
    if subject:
        sql += ' WHERE t.subject_id=?'
        params.append(subject)
    sql += ' ORDER BY t.id,a.id'
    result = {}
    for tid,name,sid,aid,question,evaluation,difficulty,kind,hint,date in db.execute(sql,params):
        item = result.setdefault(tid, {'id':tid,'name':name,'subject_id':sid,'observations':[]})
        if aid is not None:
            item['observations'].append({'id':aid,'question':question,'evaluation':evaluation,
              'difficulty':difficulty,'type':kind,'hint_used':bool(hint),'date':date})
    return result


def topic_states(db, subject=None):
    result = recent_evidence(db,subject)
    for topic in result.values():
        obs = topic.pop('observations')
        if not obs:
            state = 'unassessed'
        else:
            # Two distinct independently answered tasks, including a transfer or retrieval task.
            strong = { (o['type'], o['question'].strip().casefold()) for o in obs
                      if o['evaluation']=='correct' and o['difficulty']>=3
                      and not o['hint_used'] and o['type'] in ('practice','transfer','retrieval') }
            good_transfer = any(kind in ('transfer','retrieval') for kind,_ in strong)
            if len(strong)>=2 and good_transfer and obs[-1]['evaluation']=='correct' and not obs[-1]['hint_used']:
                state = 'demonstrated'
            elif len(obs)>=2 and any(o['evaluation'] in ('correct','partial') for o in obs):
                state = 'developing'
            else:
                state = 'emerging'
        topic['status'] = state
        topic['attempt_count'] = len(obs)
    return result


def topic_summaries(db, error_examples_per_topic=3, subject=None):
    states = topic_states(db,subject)
    rows = db.execute('''SELECT a.topic_id,a.evaluation,a.evidence,a.created_at,a.id
                         FROM attempts a WHERE a.voided=0 ORDER BY a.id''').fetchall()
    for t in states.values():
        t.update({f'{k}_count':0 for k in EVALS})
        t.update(last_result=None,last_checked_at=None,recent_errors=[])
    for tid,evaluation,evidence,date,aid in rows:
        if tid not in states:
            continue
        state=states[tid]
        state[evaluation+'_count']+=1
        state['last_result']=evaluation
        state['last_checked_at']=date
        if evaluation in ('partial','incorrect'):
            state['recent_errors'].append({'evaluation':evaluation,'evidence':evidence,'date':date,'attempt_id':aid})
    for state in states.values():
        state['recent_errors']=list(reversed(state['recent_errors'][-error_examples_per_topic:])) if error_examples_per_topic else []
    return sorted(states.values(),key=lambda t:(t['name'].casefold(),t['id']))


def due_reviews(db,subject=None,days=7,now=None):
    if days<1:
        raise TutorError('Review interval must be at least 1 day')
    now = now or datetime.now(timezone.utc)
    cutoff=now-timedelta(days=days)
    output=[]
    for t in topic_summaries(db,subject=subject):
        if not t['last_checked_at']:
            continue
        try:
            when=datetime.fromisoformat(t['last_checked_at'].replace(' ','T').replace('Z','+00:00'))
            if when.tzinfo is None:
                when=when.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if when<=cutoff:
            output.append({**t,'days_since_review':(now-when).days,'reason':'time_since_last_assessment'})
    return sorted(output,key=lambda x:(-x['days_since_review'],x['id']))


def next_topics(db,subject=None,review_days=7):
    states=topic_states(db,subject)
    requirements={tid:[] for tid in states}
    for before,after in db.execute('SELECT before_id,after_id FROM edges'):
        if after in requirements:
            requirements[after].append(before)
    ready,blocked=[],[]
    for tid,t in states.items():
        if t['status']=='demonstrated':
            continue
        unmet=sorted(p for p in requirements[tid] if p not in states or states[p]['status']!='demonstrated')
        (blocked if unmet else ready).append({**t,**({'unmet_prerequisites':unmet} if unmet else {})})
    priorities={'developing':0,'emerging':1,'unassessed':2}
    ready.sort(key=lambda t:(priorities[t['status']],t['name'].casefold(),t['id']))
    blocked.sort(key=lambda t:(t['name'].casefold(),t['id']))
    reviews=due_reviews(db,subject,review_days)
    return {'recommended_review':reviews[0] if reviews else None,'due_reviews':reviews,
            'recommended':ready[0] if ready else None,'ready':ready,'blocked':blocked,
            'rule':'Review due items; unlock new topics only when all prerequisites are demonstrated.'}


def read_json(stream):
    try:
        obj=json.load(stream)
    except (json.JSONDecodeError,UnicodeError) as exc:
        raise TutorError(f'Invalid JSON: {exc}') from exc
    if not isinstance(obj,dict):
        raise TutorError('JSON payload must be an object')
    return obj


def read_attempt_from_stdin(stream=None):
    obj=read_json(stream or sys.stdin)
    required=('topic','question','answer','evaluation','evidence')
    missing=[k for k in required if k not in obj]
    if missing:
        raise TutorError('Missing required attempt fields: '+', '.join(missing))
    if any(not isinstance(obj[k],str) or not obj[k].strip() for k in required):
        raise TutorError('topic, question, answer, evaluation and evidence must be non-empty strings')
    if obj['evaluation'] not in EVALS:
        raise TutorError('evaluation must be: '+', '.join(EVALS))
    allowed=set(required)|{'difficulty','question_type','hint_used','session_id','source_note'}
    unexpected=set(obj)-allowed
    if unexpected:
        raise TutorError('Unknown attempt fields: '+', '.join(sorted(unexpected)))
    difficulty=obj.get('difficulty',2)
    if type(difficulty)!=int or not 1<=difficulty<=5:
        raise TutorError('difficulty must be an integer 1..5')
    kind=obj.get('question_type','diagnostic')
    if kind not in KINDS:
        raise TutorError('question_type must be: '+', '.join(KINDS))
    hint=obj.get('hint_used',False)
    if type(hint)!=bool:
        raise TutorError('hint_used must be a JSON boolean')
    session=obj.get('session_id')
    if session is not None and (type(session)!=int or session<=0):
        raise TutorError('session_id must be a positive integer')
    note=obj.get('source_note','')
    if not isinstance(note,str):
        raise TutorError('source_note must be a string')
    return {**{k:obj[k] for k in required}, 'difficulty':difficulty,'question_type':kind,
            'hint_used':int(hint),'session_id':session,'source_note':note}


def add_attempt(db,a):
    require(db,'topics',a['topic'])
    if a['session_id'] is not None:
        require(db,'sessions',a['session_id'])
        ts=db.execute('SELECT subject_id FROM topics WHERE id=?',(a['topic'],)).fetchone()[0]
        ss=db.execute('SELECT subject_id FROM sessions WHERE id=?',(a['session_id'],)).fetchone()[0]
        if ts!=ss:
            raise TutorError('Attempt topic and session belong to different subjects')
    cur=db.execute('''INSERT INTO attempts(topic_id,question,answer,evaluation,evidence,difficulty,
                   question_type,hint_used,session_id,source_note) VALUES(?,?,?,?,?,?,?,?,?,?)''',
                   (a['topic'],a['question'],a['answer'],a['evaluation'],a['evidence'],a['difficulty'],
                    a['question_type'],a['hint_used'],a['session_id'],a['source_note']))
    return cur.lastrowid


def dump(obj):
    print(json.dumps(obj,ensure_ascii=False,indent=2))


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('init')
    s=sub.add_parser('subject');s.add_argument('--id',required=True);s.add_argument('--name',required=True)
    s=sub.add_parser('goal');s.add_argument('--subject',required=True);s.add_argument('--objective',required=True);s.add_argument('--depth',default='intermediate');s.add_argument('--language',default='auto');s.add_argument('--minutes',type=int);s.add_argument('--constraints',default='')
    s=sub.add_parser('session');s.add_argument('--subject',required=True);s.add_argument('--goal-id',type=int)
    s=sub.add_parser('end-session');s.add_argument('--id',type=int,required=True);s.add_argument('--summary',default='')
    s=sub.add_parser('topic');s.add_argument('--id',required=True);s.add_argument('--name',required=True);s.add_argument('--subject',default='default');s.add_argument('--description',default='')
    s=sub.add_parser('edge');s.add_argument('--before',required=True);s.add_argument('--after',required=True)
    s=sub.add_parser('attempt');s.add_argument('--json-file',type=Path)
    s=sub.add_parser('amend');s.add_argument('--id',type=int,required=True);s.add_argument('--json-file',type=Path,required=True)
    s=sub.add_parser('void');s.add_argument('--id',type=int,required=True);s.add_argument('--reason',required=True)
    for cmd in ('status','next','review'):
        s=sub.add_parser(cmd);s.add_argument('--subject');
        if cmd!='status':s.add_argument('--days',type=int,default=7)
    args=p.parse_args(argv)
    try:
        with connect() as db:
            if args.command=='init':
                dump({'ok':True,'database':str(DB_PATH),'schema_version':VERSION})
            elif args.command=='subject':
                if not args.id.strip() or not args.name.strip():raise TutorError('Subject ID and name cannot be blank')
                db.execute('INSERT INTO subjects(id,name) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name',(args.id,args.name))
                dump({'ok':True,'subject':args.id})
            elif args.command=='goal':
                require(db,'subjects',args.subject)
                if not args.objective.strip():raise TutorError('Goal objective cannot be blank')
                if args.minutes is not None and args.minutes<=0:raise TutorError('Minutes must be positive')
                c=db.execute('INSERT INTO goals(subject_id,objective,depth,language,minutes_per_session,constraints_text) VALUES(?,?,?,?,?,?)',(args.subject,args.objective,args.depth,args.language,args.minutes,args.constraints))
                dump({'ok':True,'goal_id':c.lastrowid})
            elif args.command=='session':
                require(db,'subjects',args.subject)
                if args.goal_id is not None:
                    require(db,'goals',args.goal_id)
                    sid=db.execute('SELECT subject_id FROM goals WHERE id=?',(args.goal_id,)).fetchone()[0]
                    if sid!=args.subject:raise TutorError('Goal belongs to a different subject')
                c=db.execute('INSERT INTO sessions(subject_id,goal_id) VALUES(?,?)',(args.subject,args.goal_id))
                dump({'ok':True,'session_id':c.lastrowid})
            elif args.command=='end-session':
                require(db,'sessions',args.id)
                db.execute('UPDATE sessions SET ended_at=CURRENT_TIMESTAMP,summary=? WHERE id=?',(args.summary,args.id))
                dump({'ok':True,'session_id':args.id})
            elif args.command=='topic':
                require(db,'subjects',args.subject)
                if not args.id.strip() or not args.name.strip():raise TutorError('Topic ID and name cannot be blank')
                row=db.execute('SELECT subject_id FROM topics WHERE id=?',(args.id,)).fetchone()
                if row and row[0]!=args.subject:raise TutorError(f'Topic ID "{args.id}" already belongs to subject "{row[0]}"; use a unique ID')
                db.execute('INSERT INTO topics(id,name,description,subject_id) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,description=excluded.description',(args.id,args.name,args.description,args.subject))
                dump({'ok':True,'topic':args.id})
            elif args.command=='edge':
                require(db,'topics',args.before);require(db,'topics',args.after)
                sa=db.execute('SELECT subject_id FROM topics WHERE id=?',(args.before,)).fetchone()[0]
                sb=db.execute('SELECT subject_id FROM topics WHERE id=?',(args.after,)).fetchone()[0]
                if sa!=sb:raise TutorError('Cannot connect concepts in different subjects')
                if args.before==args.after or has_path(db,args.after,args.before):raise TutorError('Edge would create a cycle')
                db.execute('INSERT OR IGNORE INTO edges(before_id,after_id) VALUES(?,?)',(args.before,args.after))
                dump({'ok':True,'edge':[args.before,args.after]})
            elif args.command=='attempt':
                if args.json_file:
                    try:
                        with args.json_file.open(encoding='utf-8-sig') as f:a=read_attempt_from_stdin(f)
                    except OSError as exc:raise TutorError(f'Cannot read UTF-8 attempt JSON file: {exc}') from exc
                else:a=read_attempt_from_stdin()
                aid=add_attempt(db,a)
                dump({'ok':True,'attempt_id':aid})
            elif args.command=='amend':
                row=db.execute('SELECT topic_id,voided FROM attempts WHERE id=?',(args.id,)).fetchone()
                if row is None:raise TutorError(f'Attempt {args.id} not found')
                if row[1]:raise TutorError(f'Attempt {args.id} is already voided')
                try:
                    with args.json_file.open(encoding='utf-8-sig') as f:a=read_attempt_from_stdin(f)
                except OSError as exc:raise TutorError(f'Cannot read amendment file: {exc}') from exc
                if a['topic']!=row[0]:raise TutorError('Amendment cannot move an attempt to another topic')
                new_id=add_attempt(db,a)
                db.execute('UPDATE attempts SET voided=1 WHERE id=?',(args.id,))
                dump({'ok':True,'voided_attempt':args.id,'replacement_attempt':new_id})
            elif args.command=='void':
                if not args.reason.strip():raise TutorError('Reason cannot be blank')
                row=db.execute('SELECT voided FROM attempts WHERE id=?',(args.id,)).fetchone()
                if row is None:raise TutorError(f'Attempt {args.id} not found')
                if row[0]:raise TutorError(f'Attempt {args.id} already voided')
                db.execute('UPDATE attempts SET voided=1,source_note=source_note||? WHERE id=?',('\nVoided: '+args.reason,args.id))
                dump({'ok':True,'voided_attempt':args.id})
            else:
                if args.subject:require(db,'subjects',args.subject)
                if args.command=='status':
                    topics=[dict(id=r[0],name=r[1],subject_id=r[2],description=r[3]) for r in db.execute('SELECT id,name,subject_id,description FROM topics ORDER BY name') if not args.subject or r[2]==args.subject]
                    edges=[dict(before=r[0],after=r[1]) for r in db.execute('SELECT before_id,after_id FROM edges') if any(t['id']==r[1] for t in topics)]
                    goals=[dict(id=r[0],subject_id=r[1],objective=r[2],depth=r[3],language=r[4],minutes_per_session=r[5],constraints=r[6]) for r in db.execute('SELECT id,subject_id,objective,depth,language,minutes_per_session,constraints_text FROM goals WHERE active=1') if not args.subject or r[1]==args.subject]
                    sessions=[dict(id=r[0],subject_id=r[1],started_at=r[2],ended_at=r[3],summary=r[4]) for r in db.execute('SELECT id,subject_id,started_at,ended_at,summary FROM sessions ORDER BY id DESC LIMIT 20') if not args.subject or r[1]==args.subject]
                    dump({'schema_version':VERSION,'subjects':[{'id':r[0],'name':r[1]} for r in db.execute('SELECT id,name FROM subjects')], 'goals':goals,'sessions':sessions,'topics':topics,'prerequisites':edges,'mastery':topic_summaries(db,subject=args.subject)})
                elif args.command=='next':dump(next_topics(db,args.subject,args.days))
                elif args.command=='review':dump({'due_reviews':due_reviews(db,args.subject,args.days)})
    except (TutorError,sqlite3.IntegrityError,sqlite3.OperationalError,ValueError) as exc:
        print(json.dumps({'ok':False,'error':str(exc)},ensure_ascii=False),file=sys.stderr)
        return 2
    return 0

if __name__=='__main__':
    sys.exit(main())
