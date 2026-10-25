---
keyflow_id: sys_social_sign_in_platform_integration
status: review
type: ai-generated
---

# Platform Integration And Other Providers

Read only the target platform section. Provider references own brand geometry;
platform adapters own activation/lifecycle; the existing auth flow owns tokens,
session state, validation and navigation.

## iOS: SwiftUI / UIKit

- SwiftUI: use `SignInWithAppleButton` from AuthenticationServices; UIKit: use
  `ASAuthorizationAppleIDButton`, optionally through `UIViewRepresentable` in
  SwiftUI/KMP hosting. Choose `.signIn`, `.signUp` or `.continue` for the flow.
- Re-evaluate style on light/dark changes. If the wrapper's button style is
  construction-only, recreate the native control without restarting auth work.
  Apply radius and sizing to the actual control, not an overlay imitation.
- For Google custom UI, preserve full-color assets with original rendering.
  Register a bundled font using `UIAppFonts` (or the target's font registration
  owner), and verify the font's actual internal name/weight at runtime.
- Keep native accessibility and localized labels; avoid duplicate logo speech
  and transparent controls over decorative fake buttons. Larger hit areas must
  not alter artwork geometry or obscure neighboring providers.

## Android / Compose / KMP

- Render Google-approved assets without Material icon tint; intentional button
  colors/padding/type override unrelated app-wide Material defaults.
- Apple custom buttons require the permission and padded artwork in the Apple
  reference. A vector conversion must retain the source viewBox/proportions.
  `Icons.*`, SF Symbols and icon fonts are not licensed artwork substitutes.
- Share semantic intent/state and stable layout rules in KMP. Keep native Apple
  controls/SDK callbacks in iOS adapters; keep Android launchers and credential
  APIs in Android adapters. Do not leak UIKit/Activity/token types into common
  button contracts or force a custom shared Apple drawing over native iOS UI.
- Dispatch one activation through the existing lifecycle owner; recomposition,
  host recreation or theme changes must not launch login again. Announce role,
  action, pending/disabled/error state; verify TalkBack and font-scale behavior.

## Web

- Prefer Google Identity Services' rendered button or current official HTML
  configurator, and Apple's supported web button/code from the HIG. Keep SDK
  configuration within supported options; never override an iframe's internals.
- Custom buttons use semantic controls, accessible localized names, keyboard
  activation, visible focus and adequate hit areas. Treat logos as decorative
  when the label already names the action. Avoid duplicate click handlers.
- Load the intended font before judging screenshots. Test narrow viewports,
  zoom, dark mode and long labels; keep all providers comparably visible.

## Kakao, Naver, GitHub And Other Providers

Use each provider's official brand kit and sign-in guidance, permitted colors,
clear space and approved action wording/localization. Equal prominence is the
shared layout baseline, not permission to recolor all logos to match the app.
When no sign-in-specific kit exists, verify trademark permissions and permitted
wording before inventing a button or claiming provider approval.

Official starting points checked 2026-10-25:
[Kakao Login](https://developers.kakao.com/docs/en/kakaologin/design-guide),
[Naver Login](https://developers.naver.com/docs/login/bi/bi.md),
[GitHub brand toolkit](https://brand.github.com/foundations/logo).
Keep provider-specific dimensions in those sources rather than applying Apple's
black/white or Google's multicolor rules to every provider.
