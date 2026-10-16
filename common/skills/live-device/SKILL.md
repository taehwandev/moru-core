---
keyflow_id: sys_common_live_device_md_skill
status: draft
type: ai-generated
---

# Live Device

Use when an Android or iOS app project may be running under Moru's Devices
Live (Android Live or iOS Live): every save of a Kotlin, Java or Swift file is
sent into the app already running on the emulator, device or simulator, in
about a second, without a reinstall or restart. Several agents may be saving
into the same running app at once.

Moru has no Live switch: it offers every device shown in its Android, iOS or
Compare Devices tool, and nothing is built until an agent starts Live from its
own worktree, so the app runs exactly the code that
agent (or its group sharing the worktree) is changing. The agent that last asked
has the device; nothing moves it on its own.

Skip when `live_device.py status` exits 5 (Live is off); build and run as the
project normally does. Run `<PROJECT>` below as your own worktree.

## Inspect First

- Whether Live runs, on which devices and for which app:
  `python3 <MORU_ROOT>/scripts/live_device.py status --project <PROJECT>`.
  Exit 0 lists lines such as
  `ios SIM-1: Live on for dev.moru.market, last applied 2026-10-16T01:05:01Z`
  for devices your worktree runs. Exit 3 means a device does not run your
  worktree's code (free, or another checkout has it): `start` when you need to
  see your change on it (Process step 1).
- Exit 4 means at least one device is still preparing or failed preparation;
  read its event and `detail`. Preparation is not proof that device is running
  Live; preserve any other devices already ready.
  For an explicit Live test, keep live verification pending until Moru reports
  ready instead of silently replacing it with a normal build/install.
- Preparation belongs to Moru's Devices plugin. Core only reads its events;
  it does not select or execute a Gradle installation task. An ambiguous task
  must be resolved from the project's actual module, variants, selected app
  and existing configuration. Do not force `:app`, `installDebug`, a Dev/Alpha
  flavor, or a specific task merely because it appears in an example or error.
- Current claims when other agents edit the same project:
  `python3 <MORU_ROOT>/scripts/path_claims.py status --project <PROJECT>`.

## Process

1. Only when the change has to be seen on a device and `status` exits 3, start
   Live from your worktree, with the deep link of the screen you will change
   when the app has one. The device comes to you from whoever had it, without
   reinstalling; nothing moves Live on its own, so ask only when you need it:
   `live_device.py start --project <PROJECT> [--platform android|ios] [--link <deep link>]`.
   It builds only when needed (a device your worktree already runs is not
   rebuilt), waits until ready (`--wait 0` returns at once) and prints one line
   per device. Agents sharing your worktree share this Live; one start is
   enough.
2. Show the screen you change: `live_device.py open --project <PROJECT> --link <deep link>`.
   After a rebuild or relaunch the plugin opens the last link again. Without a
   deep link to that screen, say which screen the user should open.
3. While Live is on, do not build, install, launch or restart the app yourself
   (no `gradlew installDebug`, `adb install`, `am start`, `xcodebuild` with a
   simulator destination, `simctl install` or `simctl launch`). Live owns the
   running app; a normal install replaces the Live build and ends Live for
   every agent. Compile-only checks that write elsewhere are fine.
4. Claim the files you will edit when another agent may be working in the same
   project (`path_claims.py claim --project <PROJECT> --path <file>`), and
   release them when done, as the `live-web` card describes.
5. Save small, complete edits. Each save is compiled and sent as it is, so a
   half-written file shows up as a failed save.
6. After saving, wait about 2 seconds, then read what reached the app:
   `live_device.py check --project <PROJECT> --files <changed files> --since <time before the save>`.
   One line per running device, such as
   `android emulator-5554: applied 2026-10-16T01:05:00Z app/.../PromoBanner.kt in 1.6s`.
   Exit 0: every device has the change. Exit 4: a device reports `failed`
   (fix the compiler error in `detail`, save again) or its automatic rebuild
   failed (read `status`; do not install it yourself). Exit 5: a device has no
   result yet or is `rebuilding and relaunching by itself`; wait and run it
   once more. A file only one platform builds (a `.kt` file on iOS) never gets
   a result from the other device; check each platform's files.
7. Know what does not go live:
   - Android: resources (`res/`), the manifest and Gradle files make the
     plugin rebuild and relaunch the app by itself, also after a branch
     switch. `remember` state in the composable you edited resets.
   - iOS: adding, changing or removing a stored property, or deleting a type
     or file, makes the plugin rebuild and relaunch the app by itself; app
     state is lost, so prefer computed properties and functions when the
     design allows it. UIKit screens show a change only when they redraw.
8. Release your claims, also after a failure. When your worktree's work is
   done (the last agent of a group, not each one), hand the device back:
   `live_device.py stop --project <PROJECT>`. The app keeps running; the next
   worktree's `start` builds its own code.

## Common Rationalizations

| Rationalization | Required Response |
| --- | --- |
| "I should rebuild to be sure the change is in." | Run `check`; installing replaces the Live build for every agent. |
| "It compiled in my head, so it applied." | Run `check`; a failed save keeps the app on its last good code. |
| "The user will see it on the device." | Report the `check` line; screenshot only on request. |
| "Only my platform matters." | When the change was asked for both apps, check both devices. |
| "Live is armed, so I start it for every task." | Start only when the change must be seen on a device; a start builds. |
| "Another checkout runs Live, so I install my build anyway." | Never; `start` brings Live to you without a reinstall. |

## Do Not

- Do not install, relaunch or kill the app, emulator or simulator while Live is on.
- Do not stop or restart the Live plugin process; hand Live back with `stop`.
- Do not `start` on a device another worktree runs, or `stop` one you do not run.
- Do not say a change is done while its latest `check` exits 4.
- Do not edit `.moru/live-device/events.jsonl`; only Moru writes it.
- Do not fix a preparation failure by changing the app's build variants or
  installing a different variant without an established project target.

## Stop If

- `check` reports that the automatic rebuild failed and `status` shows a
  build error you cannot fix in the app's code.
- The fix needs a file another agent has claimed and the user has not decided
  who goes first.

## Verification

- `live_device.py check --project <PROJECT> --files <changed files> --since <time>` exits 0.
- `path_claims.py status --project <PROJECT>` shows none of your claims.
- After `stop`, `live_device.py status --project <PROJECT>` no longer lists the
  device as run from this worktree.

## Report

Report the files changed, the last `check` line for each device, any rebuild
the user has to start, the claims taken and released, and whether you started
and stopped Live.
