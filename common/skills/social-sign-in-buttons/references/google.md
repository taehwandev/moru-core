---
keyflow_id: sys_social_sign_in_google
status: review
type: ai-generated
---

# Google Button Rules

Use for Google buttons. Source check: 2026-10-25 against the
[official branding guide](https://developers.google.com/identity/branding-guidelines).
Branding is part of app verification. Prefer current Google Identity Services
rendering or the guide's configurator/downloads before building a custom button.

| Theme | Fill | Inside stroke (1 px) | Text |
| --- | --- | --- | --- |
| Light | #FFFFFF | #747775 | #1F1F1F |
| Dark | #131314 | #8E918F | #E3E3E3 |
| Neutral | #F2F2F2 | None | #1F1F1F |

Custom typography: Google Sans Medium, reference size/line height 14/20.
Reference horizontal spacing is leading / logo-to-text / trailing: Android/web
12 / 10 / 12 px; iOS 16 / 12 / 16 px. Use approved rectangular or pill artwork
and preserve proportions when scaling; do not stretch the logo independently.
Keep the current official multicolor G, including on the approved dark/neutral
themes. Never recolor, redraw, substitute a letter/icon font or reuse an old G.

Use an approved localized action: Sign in with Google / Sign up with Google /
Continue with Google. A provider name alone is not an action label. Google's
approved icon-only mode still needs a button boundary and accessible name;
do not invent an unlabelled standalone-logo control. Keep its size and visual
weight comparable to other third-party options.

## Installed SDK Check

Inspect the resolved version and screenshot, not just the API name. For example,
[GoogleSignIn-iOS 9.2.0 GoogleSignInButton source](https://github.com/google/GoogleSignIn-iOS/blob/9.2.0/GoogleSignInSwift/Sources/GoogleSignInButton.swift)
still selects Roboto Bold, so that SwiftUI control is not a shortcut to the
current typography. Use a compliant custom button or a verified updated
renderer while retaining the authentication SDK. Recheck future versions;
this is a dated finding, not a permanent ban on Google's native controls.

## Font License And Size

Download the exact family from [Google Fonts](https://fonts.google.com/specimen/Google+Sans)
and verify its bundled license; do not substitute Product Sans. The official
[Google Sans repository license](https://github.com/googlefonts/googlesans/blob/main/OFL.txt)
is SIL OFL 1.1. Preserve copyright/license notices with redistributed fonts and
check reserved-name requirements for modifications.

If bundle size matters, use fonttools to instantiate weight 500 and subset to
all supported localized labels, punctuation and shaping needs; verify permitted
modifications first. Keep notices with the output and test actual font loading,
fallback glyphs and every supported locale. Do not promise a fixed subset size
or keep only the English label's glyphs in a localized product.
