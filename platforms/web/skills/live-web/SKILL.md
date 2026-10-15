---
keyflow_id: sys_platforms_web_live_web_md_skill
status: draft
type: ai-generated
---

# Live Web

Use when a user points at a running web page through an inspect reference line
and asks an agent to change it, or when several agents edit one web project at
the same time and each owns an area the user assigned.

Skip for ordinary web work with no inspect reference and no other agent
editing the same project.

## Inspect First

- The reference line the user pasted. It looks like:

  ```text
  [Moru Inspect] src/components/Header.tsx:42:5 <Header> button "Sign in" (#nav > button.primary) 120x44 @ Desktop
  ```

  Read it left to right: source file, line and column of the element; the
  nearest component; the element tag; its visible text (trimmed, never input
  values); a CSS selector; the rendered size in CSS pixels; the viewport name.
  A line without `:line:column` names the file only. A line without a file
  names no source; find the owner from the component, text or selector.
- The area the user assigned to you in the prompt, such as a folder or a set
  of components.
- Current claims: `python3 <MORU_ROOT>/scripts/path_claims.py status --project <PROJECT>`.

## Process

1. Open the referenced file at the given line. Confirm the component and text
   match before editing; if they do not, search for the text or selector.
2. Claim before the first edit. Claim a folder when the change spans it:
   `path_claims.py claim --project <PROJECT> --path src/components/Header.tsx`.
   The holder defaults to `MORU_SESSION_ID`, which the workbench sets in each
   hosted terminal.
3. On a conflict (exit code 3, `held by <holder> since <time>: <path>`), either
   retry with `--wait <seconds>` when the holder is likely finishing soon, or
   stop and tell the user who holds the path. Never edit a claimed path.
4. Make the change. Stay inside your assigned area; ask before touching shared
   files another area owns.
5. Release when done, also after a failure:
   `path_claims.py release --project <PROJECT> --all`.
6. Verify from the reference and DOM information (selector, text, size). Take
   a screenshot only when the user asks for one or the change is purely
   visual and cannot be checked otherwise; screenshots cost far more tokens.

## Common Rationalizations

| Rationalization | Required Response |
| --- | --- |
| "It is a one-line change, no claim needed." | Claim it; another agent may be editing the same file. |
| "The holder is probably idle." | Wait or ask the user; claims expire on their own (30 minutes by default). |
| "A screenshot is the safest check." | Use the reference and DOM data first; screenshot only on request. |

## Do Not

- Do not edit a path that another holder has claimed, or claim outside your
  assigned area to block other agents.
- Do not delete another holder's claim file by hand.
- Do not leave claims behind when you finish or abandon the work.

## Stop If

- The reference names a file outside the project or a file that no longer
  exists and no matching text or selector is found.
- The only fix requires a path claimed by another holder and the user has not
  decided who goes first.

## Verification

- `path_claims.py status --project <PROJECT>` shows none of your claims after
  release.
- The changed element still matches the reference's selector and text, or the
  new text the user asked for.

## Report

Report the referenced element, the files changed, the claims taken and
released, and any conflict and who held it.
