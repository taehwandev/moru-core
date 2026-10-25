---
keyflow_id: sys_social_sign_in_review_checklist
status: review
type: ai-generated
---

# Sign-In Button Review Checklist

Use before approving auth UI/button/asset changes. Block on incorrect branding,
unresolved asset permission or inaccessible activation; report missing visual
evidence explicitly rather than treating compilation as visual verification.

- [ ] Current official G asset, not an outdated G, letter G, monochrome/tinted
  replacement, SF Symbol, Unicode glyph or icon-font stand-in for any provider.
- [ ] Approved action wording/localization; provider name alone is not the
  accessible action. No clipped/truncated titles at large text or narrow width.
- [ ] Comparable visible dimensions and weight across providers, with their
  individual padding/contrast intact. Apple is no smaller and not below the fold.
- [ ] Actual SDK version/output checked against today's branding; old button
  styles do not pass merely because the SDK is official. Check Google typography.
- [ ] Apple uses the native control where suitable, or documented custom-artwork
  permission. User explicitly accepted the Apple artwork DMG agreement before
  acceptance/extraction; membership and cross-platform license scope checked.
  No automated license acceptance or unapproved artwork committed.
- [ ] Font source and exact license checked; copyright/OFL notices shipped when
  required. Subsetting/weight instancing retains all supported languages and
  respects modification/naming terms; actual font load and fallback tested.
- [ ] Light/dark, long localized labels, text scaling, zoom, focus and screen
  reader output captured on affected targets. Distinguish artwork minimums from
  platform hit-target sizes; no stretched/cropped/padded-away logo geometry.
- [ ] Activation is exactly once; loading, disabled, cancellation, failure and
  retry leave the existing auth flow usable. Session/security checks remain at
  their trusted owner, and KMP native APIs remain in platform adapters.
- [ ] Current App Review 4.8 applicability/exceptions considered when relevant;
  no blanket mandate inferred solely from offering Google sign-in.

Report findings by provider/platform, with source/version, screenshot or check,
impact and smallest correction. Separate unverified runtime states from passes.
