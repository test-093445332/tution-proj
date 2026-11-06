# SQLite model (version 2)

Database path: `<workspace>/.learning/progress.db`. Workspace is current directory or explicit `ADAPTIVE_TUTOR_HOME`. Data belongs to this workspace, not to the installed skill.

- `subjects(id,name,created_at)`: separates courses; `default` is reserved for migrated v1 topics.
- `goals(id,subject_id,objective,depth,language,minutes_per_session,constraints_text,active,created_at)`: learner intent and constraints.
- `sessions(id,subject_id,goal_id,started_at,ended_at,summary)`: session history.
- `topics(id,name,description,created_at,subject_id)`: globally unique concept identifiers. Prefix IDs with subject ID (e.g. `os-vm`). A topic is an assessable skill.
- `edges(before_id,after_id)`: prerequisite DAG. Same-subject edges only. Cycle checks run in the CLI.
- `attempts(id,topic_id,question,answer,evaluation,evidence,difficulty,created_at,session_id,question_type,hint_used,voided,source_note)`: original learner evidence. Never delete legitimate student mistakes.

## Derived statuses

`unassessed` if no non-voided attempts; `emerging` if evidence exists but is insufficient; `developing` with 2+ attempts and positive/partial evidence; `demonstrated` with two distinct independently correct unhinted tasks at level >=3, one being transfer/retrieval, latest answer also independently correct. Prior v1 records acquire `question_type=diagnostic` and cannot alone prove transfer.

`status` shows all-time per-topic counts, recent errors, latest assessment and all subjects/goals plus 20 latest session summaries. It does not discard old attempts. `next` prioritizes due reviews separately, then topics with demonstrated prerequisites. `review --days N` detects last assessment at least N days ago. These are heuristics, not validated knowledge probabilities.

## Corrections and migrations

The program upgrades legacy databases to schema version 2 with `PRAGMA user_version`, preserving all topic/attempt rows. Back up `.learning/progress.db` before upgrading irreplaceable datasets. Do not open the upgraded database with an old v1 script. Use `amend` to void the original attempt and insert a corrected one, maintaining both rows; use `void` to exclude invalid attempts while retaining their audit trail. The CLI rejects references to nonexistent topics/subjects/sessions, cross-subject edges, and invalid input with short JSON errors.

Attempt input is a JSON object from UTF-8 file or stdin. Required nonempty strings: `topic`, `question`, `answer`, `evaluation`, `evidence`. Optional: `difficulty` (1–5, default 2), `question_type` (diagnostic/practice/transfer/retrieval, default diagnostic), `hint_used` (boolean, default false), `session_id` (integer), `source_note` (string). `uncertain` indicates evaluator uncertainty, not necessarily learner confidence.
