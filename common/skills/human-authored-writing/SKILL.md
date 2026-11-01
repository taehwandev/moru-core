---
name: human-authored-writing
description: "Human-Authored Writing: Use when drafting or editing user-facing prose, articles, essays, blog posts, release notes, READMEs, product/report copy, emails, or localized guides so the text reads like a thoughtful human author rather than generic AI output."
keyflow_id: sys_common_human_authored_writing_md_skill
status: stable
type: ai-generated
---

# Human-Authored Writing

Use when routed to `writing` (`editorial`) or `common/skills/human-authored-writing/SKILL.md`,
when drafting or rewriting articles, essays, blog posts, build logs, READMEs,
product/report pages, comparison tables, chart labels, or localized guides, or
when prose needs natural human voice, rhythm, and clarity.

## Draft-First Human Writing Flow

1. **Lock voice, audience, and a one-sentence thesis first.**
   - Read 2–3 nearby pages or author samples to match vocabulary level, sentence cadence, and register (for Korean articles/essays, keep plain declarative endings `~다/했다/이다` consistently once established; for talks or polite guides, keep `~합니다` consistently).
   - State the piece's core point in one concrete sentence: **who does what, why it matters, and what changes for the reader**.
2. **Write a complete, scene-led draft right away (Draft-First).**
   - Deliver a full, readable draft or rewritten section immediately so the author can read and react to real prose. Do **not** stop after a 2–3-line sample unless the genre, stance, or core thesis is genuinely undecided across incompatible directions.
   - Open long-form articles, essays, and experiment posts with a narrative title and a concrete work scene, lived observation, or testable expectation (`expectation → turn/surprise → concrete cause → decision`)—never with a dictionary definition ("X means...") or a defensive meta-disclaimer ("This is only a personal test...").
   - Lead with visible actors and concrete actions, not abstract nouns or internal runtime/CLI/validator/schema jargon. Put exact CLI flags or commands in parentheses or code blocks only where the reader runs them.
3. **Reshape paragraphs holistically—never patch prose like a code diff.**
   - Good writing lives in rhythm and transitions between sentences. Freely restructure paragraphs, collapse mechanical bullet lists into flowing prose, vary sentence length, and rewrite more than one-third of a draft whenever natural flow requires it.
   - Update directly coupled passages on the same page in the same pass so headings, body paragraphs, and conclusions tell the same story. Surface separate out-of-scope sibling pages for confirmation.
4. **Read aloud for native phrasing, reader comprehension, and factual fidelity.**
   - In Korean, Japanese, and Chinese prose, translate concrete meaning into natural native developer phrasing—never word-for-word calques of internal English compound nouns.
   - Never sacrifice natural phrasing or reader comprehension for abrupt shorthand compression. Keep the actors, conditions, and causal links a reader needs without private project context.
   - Preserve every factual commitment, number, quote, citation, and structural differentiator (placing the subject product first in comparisons and explaining *why* its mechanism solves the alternative's trade-off).

## Read

- `references/current-guidance.md` for Before/After examples, Korean/English voice calibration, comparison layout rules, and the technical evidence ladder.
- `common/skills/writing-workspace/SKILL.md` when creating or publishing long-form blog posts, essays, or articles across draft and publish directories.

## Do Not

- Do not apply code-diff restrictions ("touch only the flagged line" or "never rewrite more than 1/3 of the text") when the user asks for natural human writing or a full rewrite.
- Do not invent personal anecdotes, unverified measurements, citations, or product claims to fake "human texture."

## Verification

- Read the finished draft aloud from the intended reader's perspective: confirm the one-sentence thesis holds from title to conclusion, register and voice stay consistent, and every fact, number, and command remains accurate.
