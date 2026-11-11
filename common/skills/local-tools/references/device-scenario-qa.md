---
keyflow_id: sys_local_tools_device_scenario_qa
status: stable
type: ai-generated
---

# Connected Device Scenario QA

Use this workflow when the user asks to execute or continue a set of device
scenarios. Apply the target project's scenario, recording, access and safety
rules as well. This workflow adds no per-step hook or approval gate.

## Prepare one connected journey

Select the requested scenario scope and acceptance criteria. Read the existing
results once to find unfinished conditions and preserve already observed work;
do not rerun it unless the user asks or the applicable evidence policy requires
new evidence. Record the reason and changed condition if a rerun is needed.
Preserve actual build, device, account role, project and fixture identities;
evidence from another build or role does not prove an unobserved condition.

Choose the user's primary device and use other devices only for roles or
conditions they authorize. If no preference is given, select a device appropriate
to the criterion, name its serial, and do not silently pick the first device.
Prepare the device tool once per journey, not once per ticket. Reuse an existing
suitable and authorized project, post and account only after confirming the
needed state. Avoid recreating them for each ticket. Do not expand authority to
real-user content, irreversible actions or messages. Record prerequisites,
fixture IDs, entry point, expected transition and the next connected step.

## Execute and record

Perform contiguous steps on the selected device, observing each relevant result
and collecting the project's required UI and, where applicable, API evidence.
Use the current screen and known fixture lineage to continue; still observe the
current UI before each action as required by the device contract. Do not repeatedly
query the same history or restart the journey after every step. Record shared
prerequisites once and refer to them from subsequent steps without claiming the
later action was performed. Record defects only against an established oracle;
unknown design decisions and missing evidence remain unverified.

Record each observation through the target project's authoritative results
surface, including device, build, role, fixture and evidence links. Preserve
previous observations and honor its correction and append-only rules. Distinguish
an observed portion of a compound condition from completion of the whole step.
Apply the device contract's baseline rule before a build replacement when making
a regression or improvement claim. Protect sensitive data in retained evidence.
If storage fails, retain the observations and evidence locally, note any pending
operation, and reconcile whether it took effect before retrying. Continue other
independent authorized work if safe; do not fabricate a web receipt or result.

## Continue without duplicate claims

An automatic stop-hook continuation while the run remains active continues that
same run; this continuation does not need `resume`. At an actual turn boundary,
follow the runtime's paused-run reclaim path and ownership policy. Do not bypass
a different live owner, clear its state or start a competing worker. If the owner
cannot be resolved, record the refusal and wait for the appropriate recovery.
Check the run, owner and session once per actual ownership change or refusal;
reuse that evidence until new evidence changes it. Do not repeatedly rediscover
the same state, reopen completed scenarios or narrate an old conflict as new.
A user instruction to pause device execution stops new device actions; record
the pause in the work state so automatic continuation does not restart them.
Preserve and record observations already made when authorized.

Keep the unfinished queue tied to actual results and fixture availability.
When a prerequisite, device or service blocks only part of the scope, record
that limitation and continue independent work rather than replaying completed
steps. Report completed observations, defects, remaining conditions and any
unrecorded evidence separately; never call the whole scenario complete from
partial evidence or from the presence of connected devices.
