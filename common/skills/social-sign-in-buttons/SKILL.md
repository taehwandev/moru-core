---
name: social-sign-in-buttons
description: "Social Sign-In Buttons: Use when implementing or reviewing third-party sign-in buttons, authentication screens or their brand assets on iOS (SwiftUI/UIKit), Android, Compose/KMP or web."
keyflow_id: sys_common_social_sign_in_buttons_skill
status: review
type: ai-generated
metadata:
  internal: true
---

# Social Sign-In Buttons

## Use When

Use when implementing or reviewing third-party sign-in buttons, authentication
screens or their brand assets on iOS (SwiftUI/UIKit), Android, Compose/KMP or
web. Covers Apple, Google and other providers. Backend-only session, token or
RBAC changes retain their auth guidance without needing these UI details.

## Inspect First

- Find the button owner, installed SDK version, current rendered appearance,
  asset origin/license, supported locales, themes and accessibility settings.
- Read [Apple](references/apple.md) or [Google](references/google.md) for each
  provider touched; check linked official sources before choosing artwork or
  version-sensitive styles. If unreachable, disclose the retained source date.
- Read [platform integration](references/platform-integration.md) for the target
  platform and other providers. Use [the review checklist](references/review-checklist.md)
  before approval. Keep existing platform UI and auth enforcement contracts.

## Decision Rule

1. Prefer provider-rendered controls when their actual output matches current
   branding. Otherwise use approved assets/custom rendering within the provider's
   rules; an official SDK name alone does not prove current visual compliance.
2. Give providers equal prominence: comparable visible size and visual weight,
   accessible names, and approved localized action wording. Preserve each
   provider's colors, proportions and clear space within the common layout.
3. Keep Apple visible alongside other sign-in methods without scrolling. Choose
   order for the product/platform; no universal Apple-first or Google-first rule.
4. Separate button rendering from authentication orchestration. Expose intent
   callbacks and loading/disabled state; reuse the existing session flow.
5. Before accepting the Apple artwork DMG license, ask the user to review and
   explicitly accept it. Do not automate acceptance or infer it from a request
   to implement the button. Unrelated guidance work can continue without assets.

## Do Not / Stop If

- Do not redraw logos, use a text letter G, SF Symbol, Unicode Apple glyph or
  icon-font stand-in, tint a multicolor logo, or crop away supplied clear space.
- Stop asset incorporation when provenance, license permission, or user license
  acceptance is unresolved. Do not ship a placeholder as a compliant button.
- Do not treat a brand-compliant button as proof of secure authentication or
  App Store eligibility; validate the existing auth boundary separately.

## Verification

Compile affected targets and capture the rendered screen in light/dark themes,
supported locales, large text and a narrow viewport. Compare with current
provider artwork, check prominence and focus/VoiceOver/TalkBack/keyboard access,
and exercise one activation, pending, cancellation, error and retry path.

## Report

Name providers/platforms, SDK versions, official sources and verification date,
asset/font licenses and acceptance status, rendered evidence, behavior checks
and any unverified states. Never claim artwork was licensed from a screenshot.
