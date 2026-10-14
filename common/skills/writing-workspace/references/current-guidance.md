---
keyflow_id: sys_writing_workspace
status: stable
type: human-reviewed-needed
---

# Writing Workspace

Use when an agent is asked to draft, revise, review, or publish a blog post,
article, essay, public announcement, release narrative, or other durable prose
that may later be copied into a website, docs repo, newsletter, social channel,
or publishing system.

This card defines where writing work should live. Use
`common/skills/human-authored-writing/SKILL.md` for voice, fidelity, and AI-writing signal
cleanup.

## Use When

- The user asks for a blog post, article, essay, public introduction, or
  publishable long-form prose.
- The user asks to write in the author's style or keep writing consistent across
  agents.
- The target could be confused with an app, web, docs, or publishing repo.
- A product has multiple repos and only one of them is the final publishing
  surface.

## Inspect First

- The user's requested audience, language, channel, and whether the task is
  draft-only, review-only, publish-ready, or direct-publish.
- Repo-local writing rules, brand rules, content templates, and public discovery
  rules.
- A configured writing workspace from the user's explicit path, repo-local
  instructions, or local project registry such as
  `~/.moru/projects.json`.
- Two or three approved author voice samples when the user asks for a consistent
  personal voice.
- The publishing target only after the writing workspace is identified or the
  user explicitly asks to publish into that target.

## Decision Rule

Use a dedicated writing workspace as the source of truth for new long-form
drafts when the user does not explicitly name a file or publishing repo path.

Do not default a blog or article request to a web/app repository merely because
that repository renders the final site. Treat web, app, docs, newsletter, and
CMS repos as publishing targets, not default draft owners.

If no writing workspace is configured, ask one short location question before
creating or editing article files. Recommend a separate portable workspace,
registered with aliases such as `writing`, `blog`, `articles`, or `drafts`.
Do not imply that every article must stay in `drafts/`; publishing, archival,
or explicitly named paths override the default.

## Workspace Model

A writing workspace only needs enough structure for agents to find the current
writing source of truth. At minimum, it should contain a local instruction file
and one documented location for active writing.

Optional folders can make repeated work easier:

- `drafts/`: active drafts, usually named with date or topic slug.
- `articles/` or `posts/`: a neutral active-writing folder when the workspace
  does not want to separate drafts from later versions.
- `published/` or `archive/`: final versions when the workspace owns archived
  prose.
- `voice/`: approved author voice samples, style notes, or links to public
  posts.
- `references/`: source links, research notes, product facts, screenshots, or
  quotes that are safe to use.
- `templates/`: optional article, release note, or announcement outlines.

These names are examples, not required structure. Do not create all of them by
default. A repo-local content system may use different folders if it documents
them.

## Local Registry Guidance

When agents need to discover the workspace automatically, register it in the
local project registry instead of hard-coding personal paths into shared docs:

```json
{
  "projects": [
    {
      "root": "<WRITING_WORKSPACE_PATH>",
      "aliases": ["writing", "blog", "articles", "drafts"]
    }
  ]
}
```

For a product with a separate web publishing repo, use a workspace group so the
writing workspace can be selected as primary for drafts and the web repo can be
treated as a secondary publishing target.

The workspace should contain a local instruction file such as `AGENTS.md` so
project discovery can select it as a real writable workspace instead of treating
it as a plain folder.

## Process

1. Classify whether the request is draft, revision, review, publish, or
   cross-posting work.
2. Resolve the writing workspace before opening a publishing repo.
3. Load author voice samples from the configured workspace or approved public
   posts.
4. Draft in the writing workspace unless the user explicitly names a target
   file. Use the workspace's documented active-writing folder; `drafts/` is only
   the default when no other folder is documented.
5. Keep source links and protected claims with the draft.
6. If publishing is requested, stop for a workspace scope checkpoint before
   writing into the publishing repo.
7. Verify frontmatter, links, public-discovery metadata, and build/render checks
   in the publishing repo only when that repo is part of the requested scope.

## Common Rationalizations

| Rationalization | Required response |
| --- | --- |
| "The website repo renders the blog, so it must be the draft location." | Use the writing workspace for drafts; use the website repo only when publishing is requested or explicitly named. |
| "The user said blog, so any markdown folder is fine." | Resolve the configured writing workspace or ask for one before creating files. |
| "Every article must go in `drafts/`." | Use `drafts/` only as the default for unspecified new writing; explicit files, publishing targets, and documented workspace folders win. |
| "A personal absolute path is convenient." | Store personal paths only in local runtime config or project registry, not in committed shared guidance. |
| "The article is done once the prose reads well." | Preserve source links, protected claims, voice sample evidence, and publish-target checks when publishing is in scope. |

## Red Flags

- A draft is created inside an app, web, or deployment repo without an explicit
  publish request.
- The draft has no source links for factual claims.
- The agent uses a personal voice without checking approved samples.
- The agent edits a publishing repo before recording whether the work is
  draft-only or publish-ready.
- Multiple agents produce blog drafts in different folders for the same author
  or product.

## Do Not

- Do not put shared Moru Core rules for a single person's personal path,
  blog engine, or publishing repo.
- Do not write drafts into generated site output, build artifacts, or public
  HTML folders.
- Do not publish or modify a web/CMS repo unless the user requested publishing
  or explicitly named that path.
- Do not copy private notes, source snippets, or unpublished references into a
  public publishing repo without checking the public boundary.
- Do not invent dates, citations, claims, screenshots, or personal experience to
  make an article feel complete.

## Stop If

- No writing workspace is configured and the user did not name a target file.
- The request requires publishing, but the publishing target, branch, preview,
  metadata, or public URL is ambiguous.
- The article depends on private source material that is not available or not
  safe to publish.
- The user asks to imitate a third-party private voice instead of using approved
  author-owned samples or broad style descriptors.

## Verification

For draft-only work:

- The file is in the configured writing workspace or the explicitly named path.
- Protected facts, links, names, dates, and claims are preserved.
- Voice samples or style assumptions are recorded.

For publish-ready work:

- Draft source and publishing target are distinguished.
- Public discovery metadata, canonical URLs, and previews are checked when
  relevant.
- The publishing repo's frontmatter/link/build/render checks pass or the
  residual risk is reported.

## Report

When this card governs the work, report:

- the writing workspace or explicitly named path used
- whether the work was draft-only, review-only, or publish-ready
- the voice/source samples used
- whether a publishing repo was intentionally untouched or updated
- verification run and remaining publishing risk
