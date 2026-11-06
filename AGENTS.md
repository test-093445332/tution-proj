# Adaptive Tutor — Codex project instructions

This is a local, standalone adaptive-learning workspace. Use the bundled `.agents/skills/adaptive-tutor/SKILL.md` whenever the user wants teaching, diagnosis, exercises, revision, or study planning. Use Codex's normal existing authentication. No external notebook service, API key, or local model is required.

**Non-negotiable assessment persistence:** After EACH actual learner answer to a substantive assessment prompt, write a JSON attempt with the exact response, assessment type, hint use, difficulty and non-empty evidence, then successfully invoke `progress.py attempt --json-file ...` BEFORE giving the next scored question. Do not proceed silently if persistence fails. Do not invent an attempt for a skipped question. Resolve errors using returned JSON error messages. Use a file-writing tool to create the payload; never paste learner-controlled text into a shell command. Keep the project work directory fixed so the correct `.learning/progress.db` is used.

Always start/resume with `status` and `next`, separating subjects and their stored goals/sessions. Keep a single question per exchange; prioritize independent transfer and periodic review. Verify unfamiliar facts with reliable sources when possible and disclose uncertainty instead of hallucinating.

When the user asks for programming or other non-tutoring work, follow their actual request rather than force a lesson.
