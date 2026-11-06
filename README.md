# Adaptive Tutor for Codex CLI

A minimal local adaptive tutor that **teaches subjects even when no notes exist**. It uses the host Codex login, a reusable English Skill, and Python's standard-library SQLite. No additional API, local model, Obsidian, or service is required. This is a prototype: status rules and review intervals are explicit heuristics, not validated learning-science scoring.

## Quick start

1. Unzip this project and open a shell **in its root**.
2. Install Python 3.10+ and Codex CLI, and sign into Codex using your existing ChatGPT account if necessary.
3. Run `codex` and type:

   `Use the adaptive-tutor skill. Teach me operating systems in Russian. Start by assessing what I know, ask one question at a time, record my answers, and recommend what to study next.`

Codex reads `AGENTS.md`, which requires recording every assessed answer. The SQLite database is created at `.learning/progress.db`. Files in `.learning/` are private study data and are gitignored.

## Windows PowerShell

If Python Launcher is installed, use `py -3`; otherwise `python`:

```powershell
py -3 .agents/skills/adaptive-tutor/scripts/progress.py init
py -3 .agents/skills/adaptive-tutor/scripts/progress.py status
py -3 .agents/skills/adaptive-tutor/scripts/progress.py next
py -3 -m unittest discover -s tests -v
codex
```

Always use `--json-file .learning/pending-attempt.json` to record learner answers on PowerShell; the `<` input-redirection syntax from Bash does **not** work there. Use UTF-8 JSON, including Unicode and newlines. The CLI also accepts UTF-8 BOM. If native Codex CLI has terminal/runtime issues, use WSL and run everything (including the Python tool) inside the same WSL study directory. Codex availability and feature support depend on its installed version and account entitlements.

## Linux / WSL / macOS

```bash
python3 .agents/skills/adaptive-tutor/scripts/progress.py init
python3 -m unittest discover -s tests -v
codex
```

On Bash, `attempt < .learning/pending-attempt.json` is supported, as is `attempt --json-file .learning/pending-attempt.json`. Do not interpolate free-form learner responses in shell commands on any OS.

## CLI walkthrough

Replace `python3` with `py -3` / `python` as appropriate:

```bash
T=.agents/skills/adaptive-tutor/scripts/progress.py
python3 "$T" subject --id os --name "Operating systems"
python3 "$T" goal --subject os --objective "Understand virtual memory" --depth intermediate --language ru --minutes 30
python3 "$T" session --subject os --goal-id 1
python3 "$T" topic --subject os --id os-memory --name "Virtual memory"
python3 "$T" topic --subject os --id os-pages --name "Page tables"
python3 "$T" edge --before os-memory --after os-pages
python3 "$T" status --subject os
python3 "$T" next --subject os
python3 "$T" review --subject os --days 7
```

The `T=...` shortcut above is for Bash, not PowerShell. For PowerShell, use the full script path as in the Windows example.

The tutor creates `.learning/pending-attempt.json` using a file-writing tool and then runs `progress.py attempt --json-file .learning/pending-attempt.json`. Example:

```json
{
  "topic": "os-memory",
  "session_id": 1,
  "question": "Why do processes need virtual address spaces?",
  "answer": "A verbatim learner answer, including quotes and line breaks",
  "evaluation": "partial",
  "evidence": "Explains isolation but not mapping of virtual to physical pages",
  "difficulty": 3,
  "question_type": "diagnostic",
  "hint_used": false,
  "source_note": "Source title/URL if verified; otherwise empty"
}
```

`status` aggregates **all attempts per topic**. `next` returns eligible concepts, blocked prerequisites, and due-review suggestions. `amend --id 4 --json-file replacement.json` replaces an erroneously recorded assessment while retaining audit history. `void --id 4 --reason "Duplicate"` excludes an invalid attempt from computed mastery.

## Workspace separation and global installation

The default data directory is the process's current directory. Set `ADAPTIVE_TUTOR_HOME` to use a different workspace. The Skill may live at `.agents/skills/adaptive-tutor/` inside this project or be installed globally. In either case, call its helper by its actual path and keep the process working directory pointing at the desired study workspace. Avoid using old CLI versions against an upgraded database. Always make a backup before migrating irreplaceable data.

## Known limitations

- Mastery status is a conservative rules-based heuristic, not Bayesian Knowledge Tracing.
- Review scheduling uses a fixed configurable day threshold, not FSRS or Anki scheduling.
- Accuracy of self-generated study maps and factual questions depends on model reasoning and available trustworthy references; unverified niche facts should not be presented with false confidence.
- There is no GUI, remote sync, external connector, or guaranteed automatic evaluation independent of the host agent's compliance with AGENTS.md.
