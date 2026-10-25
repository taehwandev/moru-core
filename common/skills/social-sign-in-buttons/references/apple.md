---
keyflow_id: sys_social_sign_in_apple
status: review
type: ai-generated
---

# Apple Button Rules

Use for Apple button rendering; source check: 2026-10-25 against the
[HIG](https://developer.apple.com/design/human-interface-guidelines/sign-in-with-apple)
([Markdown](https://developer.apple.com/design/human-interface-guidelines/sign-in-with-apple.md)).

- Prefer SwiftUI `SignInWithAppleButton` or UIKit `ASAuthorizationAppleIDButton`.
  They supply approved proportions, localized titles and accessibility labels.
  Match the radius to neighboring controls, including capsule shapes.
- Use black on light backgrounds, white on dark backgrounds, or white outline
  on light backgrounds. Retain contrast after appearance changes.
- Titles: Sign in with Apple / Sign up with Apple / Continue with Apple;
  choose the matching system variant and approved localization.
- HIG minimum for a titled button: 140 × 30 pt (web: CSS px at 1x); surrounding
  clearance at least 10% of height. This artwork minimum does not replace the
  platform's accessible hit-target requirement. Never make Apple smaller than
  peer sign-in controls or hide it below the fold.

## Custom Artwork And Permission

For custom controls, including Android, obtain sign-in-specific artwork from
[Apple Design Resources](https://developer.apple.com/design/resources/), not a
general Apple logo. The official
[artwork DMG](https://devimages-cdn.apple.com/design/resources/download/Logo-Sign-in-with-Apple.dmg)
has a Developer Artwork License Agreement for Sign in with Apple.

Ask the user to review and explicitly accept the agreement before acceptance,
mounting or extraction that requires agreement; never pass an automatic accept
response. Check current membership, permitted UI use and cross-platform terms
with that user. The supplied 2026-10-25 notes describe Developer Program
membership and other-platform versions with the same title/equivalent features;
the DMG agreement was not independently accepted or extracted for this guide.
Do not infer that public download availability permits redistribution here.

After permission, use the supplied black/white SVG/PDF/PNG with its padding.
Match the entire artwork file height to the button height; do not crop or add
vertical padding. Logo and title share black or white; background remains
black or white. Prefer system type; its reference title size is 43% of button
height. Keep trailing title clearance at least 8% of button width. PNG artwork
is for the HIG's 44 pt reference; use vector artwork for other sizes. Logo-only
controls use the dedicated square artwork and an accessible action name.

## App Review Scope

Recheck [App Review 4.8](https://developer.apple.com/app-store/review/guidelines/#login-services)
when third-party login establishes the primary app account. It calls for an
equivalent privacy-preserving login option (limited collection, private email,
no advertising interaction collection without consent) and lists exceptions,
including own-account-only, enterprise/education and specific-service clients.
Sign in with Apple is a usual way to meet the requirement; do not reduce the
current rule to “Google always requires Apple.” Custom buttons also face review.
