---
keyflow_id: sys_human_authored_writing
status: stable
type: human-reviewed-needed
---

# Human-Authored Writing

Use when drafting or editing user-facing prose, articles, essays, blog posts, build logs, READMEs, release notes, product/report copy, emails, or localized guides where the goal is natural human voice, clear judgment, and reader comprehension.

This card is for writing quality, voice fidelity, and clarity. It is not an instruction to deceive reviewers, bypass AI detectors, or evade disclosure rules where disclosure is required.

## Why Prose Is Not Code Patching (Draft-First Autonomy)

Code workflows minimize diff lines and touch only the failing span. Applying those habits to prose produces stiff, stitched-together paragraphs that sound like a template filling in blanks.

- **Write the full draft first, then iterate fast.** When the user's topic, genre, and target file or channel are clear, write or rewrite the complete piece immediately. Human writing is fastest to evaluate by reading a real draft and adjusting tone or emphasis in follow-up turns.
- **Ask before drafting only when the direction is genuinely open.** Pause with a brief 2–3-line sample or mode choice only when the request could mean incompatible genres (for example, an objective reference guide vs. a first-person opinion essay) or when a thesis change would require editing separate unrequested sibling pages.
- **Restructure paragraphs freely.** Do not restrict yourself to span-only edits or an artificial one-third rewrite cap when a draft sounds robotic. Merge repetitive bullets into coherent paragraphs, cut throat-clearing introductions, vary sentence lengths, and rebuild transitions so the piece reads as one continuous thought.
- **Protect deliberate author hand-edits and facts.** While structure and phrasing are flexible in a draft or rewrite, never alter facts, numbers, dates, quotes, citations, legal/policy commitments, or specific phrases the author deliberately locked in.

## The 4-Step Human Writing Process

### 1. Lock Voice, Register, and a One-Sentence Thesis

- **State the thesis in one concrete sentence** before writing: *who does what, why it matters, and what changes*. Check that the title, opening, section headings, and ending all advance that single point.
- **Calibrate to 2–3 real samples** (existing repo pages, previous posts, or the user's draft fragments):
  - **Korean register lock:** Once author samples or the draft establish plain declarative endings (`~다`, `~했다`, `~이다`), keep that register through the entire piece. Do not drift into honorific explanatory endings (`~합니다`, `~됩니다`, `~보입니다`) mid-article. Conversely, a spoken talk or presentation script keeps its spoken honorific register (`~합니다`) throughout.
  - **Honor author vocabulary and negative voice evidence:** When the author prefers specific wording (e.g., `분석` over `조사`, `나눠서 작업(하다)` over `나눠서 맡기다`, `스킬` over `프롬프트`) or rejects a phrase, metaphor, or framing, record it in the project/author voice file and remove both the exact phrase and its underlying pattern across the whole artifact.
  - **Series continuity:** When continuing a series, verify what the *published* predecessor actually covered rather than assuming unpublished local draft notes were seen by readers.

### 2. Draft-First with Concrete Scenes and Active Actors

- **Open long-form essays and experiment posts with inquiry, not definitions:**
  - Craft a title that captures the expectation, reversal, or central question rather than a dry report label.
  - Start with a concrete work scene, lived frustration, or universal intuition paired with a clear pivot question (*"What actually happened when we measured it?" / "실제로 재 보면 어떨까?"*).
  - Sequence sections around the inquiry arc: **expectation → turn/surprise → concrete mechanism/cause → decision**.
  - Group methodology limits in one clean note instead of attaching defensive disclaimers to every paragraph, and include a cover thumbnail (`cover:`) plus inline diagrams when visual assets are in scope.
- **Name visible actors and actions:** Replace abstract nominalizations ("layer ownership instability", "execution of deterministic validation") with who acts and what happens ("when two modules edit the same state, callers cannot tell which update wins").
- **Escalate with the Evidence Ladder when prose alone is not enough:**
  1. **Direct prose** for one actor and one action (who calls, reads, or changes what, and the outcome).
  2. **Compact diagram, sequence, or table** when three or more parts interact or dependency/lifecycle direction matters.
  3. **Smallest code, config, or signature example** when the point depends on exact syntax, compile-time visibility, or a rule with a narrow exception—followed by the cost and when *not* to use it.

### 3. Translate Internal Mechanics for Readers and Comparisons

Internal gate names, schema keys, validator slugs, and CLI flags belong in runtime code, not user-facing headings, chart labels, or comparison rows.

1. **State the observable action and outcome first:** Write *"Answer questions right away without extra steps"* instead of *"Stateless Read-Only Fast Path"*, or *"Reuse passed tests when code hasn't changed"* instead of *"Input-attested byte-hash continuation"*. Place exact CLI flags or commands in parentheses or code blocks only where the reader runs them.
2. **Label metrics in everyday units:** Use *"Rule files read per task"*, *"Steps per task"*, or *"Token usage per task"* as primary labels; put statistical qualifiers (`median / p50`, cohort formulas) in captions or methodology notes.
3. **Never calque internal compound nouns word-for-word in localized copy:** In Korean, Japanese, or Chinese, replace stiff literal calques (`결정론적 라우트 명세`, `무상태 Read-Only Fast Path`, `참조 가중 토큰 중앙값`) with natural native developer phrasing (`지금 할 일에 필요한 규칙 문서만 골라 읽습니다`, `단순한 질문에는 절차 없이 바로 답합니다`, `작업 한 번에 쓰는 토큰 양`).
4. **Put the subject product first and preserve its structural differentiator:** In comparison tables and responsive card stacks, always place the subject product in the first comparison column or top hero card (never hidden at the far right of a horizontal-scrolling table). When simplifying wording, keep the concrete mechanism and trade-off that explain *why* it wins (e.g., zero-LLM section indexing in milliseconds vs. spending extra LLM turns searching raw chat logs; test-verified rule fixes with expiry dates vs. unverified auto-edits that accumulate stale rules).

### 4. Read-Aloud Rhythm & Semantic Completeness Pass

- **Never trade comprehension for compression:** Concision cuts filler; over-compression cuts the context the writer knows privily but the reader cannot guess. Do not cram meaning into abrupt shorthand or mismatched idioms in Korean (such as compressing *"context from earlier in the conversation"* into “앞말”, over-dramatizing fatigue as “내 진을 빼놓는”, or shrinking *"measuring token overhead and trimming what isn't needed"* into “재 보고 덜어내는”).
- **Vary cadence naturally:** Mix short direct sentences with longer explanatory ones. Cut mechanical transitions (*"Moreover," "Furthermore," "이 글에서는," "중요한 점은"*), rule-of-three padding, and conclusions that merely repeat the introduction instead of landing a decision or takeaway.
- **Reconcile coupled passages together:** When a headline, thesis, or term changes, update adjacent paragraphs on the same page in the same pass and reread them together so the page never contradicts itself.

## Concrete Before / After Examples

| Pattern | Robotic / Over-Compressed / Calqued (Before) | Natural Human-Authored (After) |
| --- | --- | --- |
| **Long-form opening (Korean)** | 이 글에서는 에이전트 워크플로우의 토큰 오버헤드를 정의한다. 본 측정은 공식 벤치마크가 아니며 개인 환경에서 수행된 참고용 수치임을 먼저 밝힌다. | 에이전트에게 열 줄짜리 버그 수정을 시켰는데 시작도 하기 전에 규칙 문서만 아홉 개를 읽고 있었다. 안전하자고 만든 절차가 정작 작업 자체보다 무거워진 셈이다. 실제로 토큰이 어디서 새는지 직접 재 보기로 했다. |
| **User-facing feature copy (Korean)** | **결정론적 라우트 명세 및 무상태 Read-Only Fast Path**: 입력 검증 바이트 해시 연속성을 통해 중복 감사를 생략합니다. | **지금 할 일에 필요한 규칙만 골라 읽고, 단순 질문에는 바로 답합니다**: 코드가 바뀌지 않았다면 이미 통과한 검사를 다시 돌리지 않습니다. |
| **Semantic over-compression (Korean)** | 앞말을 다 들고 다니면 내 진을 빼놓으니 재 보고 덜어내는 구조가 필요하다. | 대화 초반에 나눴던 맥락까지 매 턴 프롬프트에 통째로 실어 보내면 토큰도 빨리 닳고 응답도 느려진다. 어느 단계에서 토큰을 많이 쓰는지 먼저 측정한 뒤, 지금 작업에 필요 없는 규칙부터 덜어내야 한다. |
| **Technical & product prose (English)** | This architecture plays a pivotal role in fostering seamless multi-agent orchestration—unlocking deterministic quality while ensuring comprehensive safety across diverse workflows. | When three agents edit the same repository at once, they overwrite each other's files unless each worker gets its own Git worktree and file scope before writing a line of code. |

## Compact Post-Draft Lint

| Surface | Signals to cut or rewrite |
| --- | --- |
| **Korean prose** | Translationese (`~을 통한`, `~에 있어서`), unnecessary formal nouns (`것/점/수/바`), honorific drift (`~합니다` mixed into `~다`), stock AI frames (`핵심은`, `중요한 점은`, `반대로`), and non-authorial metaphors (`금방 갈라진다`) where concrete maintenance wording fits better. |
| **English prose** | Inflated significance (`pivotal`, `crucial`, `testament`), promotional verbs (`unlock`, `empower`, `streamline`), shallow `-ing` participial tails (`...ensuring seamless integration`), excessive em dashes, fake balance (`While X, Y`), and synonym cycling. |
| **Documentation & UI** | Raw internal gate/flag/schema names in headings, "this guide explores" throat-clearing, diff-anchored narration, and uncalibrated tone. For UI/localized strings, also apply `common/skills/accessibility-i18n/SKILL.md`. |

## Do Not / Stop If

- **Do not** promise AI-detector bypass, invent lived anecdotes/sources/numbers, or rewrite direct quotes, legal/regulated text, or policy commitments without explicit authority.
- **Do not** casualize institutional/legal documents or force personal-essay framing when the user only asked for plain declarative sentence endings (`~다`).
- **Stop and ask** only if the user asks to misrepresent authorship/evade required disclosure, if required factual sources are missing, or if choosing between incompatible genres/theses would reshape the entire piece.

## External References

Checked on 2026-06-27 as background inspiration (never copy as source text): `epoko77-ai/im-not-ai`, `blader/humanizer`, `harshaneel/humanize`, `jpeggdev/humanize-writing`, `orange2ai/writing-style-guard`, `fendouai/best-humanizer-handbook`, `viktorbezdek/definitive-llm-writing-style-guide`, and `shaswatco/anti-ai-writing-style`.
