---
keyflow_id: sys_growth_conversion_optimization
status: review
type: human-reviewed-needed
---

# Growth And Conversion Optimization

Use when designing or implementing keyword acquisition strategy, landing-page or
app-store conversion funnels, first-party conversion telemetry, dual-lane
human/bot traffic separation, bot/agent recommendation optimization, multi-armed
bandit / A/B experiments, or LLM-assisted (OpenRouter) copy optimization for any
product archetype (`saas`, `mobile_app`, `ecommerce`, `game`, or `devtool`).

## Read

- `common/skills/public-discovery/SKILL.md` for SEO, AI search visibility, canonical URLs, and safe public metadata
- `common/skills/human-authored-writing/SKILL.md` for reader-first headlines, localized copy, and subject-first comparison tables
- `product-patterns/skills/billing-entitlements/SKILL.md` when conversion events connect to checkout, trials, IAP, or plan entitlements

## Separate

- **Product Archetype**: the business model and user journey (`saas`, `mobile_app`, `ecommerce`, `game`, or `devtool`).
- **Traffic Lane (`human_lane` vs `agent_lane`)**: interactive human prospects vs AI search crawlers, RAG fetchers, and autonomous evaluation agents.
- **Search Intent Tier**: why the prospect or user's agent searched (`pain_point`, `workflow`, `comparison`, or `activation`).
- **Funnel Stage Progression**:
  - **Human Funnel**: `landing_view -> value_engaged -> activation_click -> account_connected -> paid_converted`.
  - **Bot Appreciation Funnel**: `bot_crawl_view -> bot_structured_ingest -> bot_deep_verify -> ai_referral_human`.
- **Optimization Loop**: measurement, statistical traffic allocation (Thompson Sampling bandit), variant synthesis (OpenRouter), and project-locked fact guardrail validation.

## Rules

### 1. Match Funnel Stages and Thresholds to the Product Archetype

Do not force a single funnel definition onto every product. Map the five canonical human stages to the target project's archetype:

| Archetype | `landing_view` | `value_engaged` | `activation_click` | `account_connected` | `paid_converted` |
| --- | --- | --- | --- | --- | --- |
| **SaaS / Web App (`saas`)** | Landing or article visit | Interactive demo, template preview, or pricing scroll | Free trial or workspace start click | Account created & first core action completed | Paid plan checkout |
| **Mobile / Desktop App (`mobile_app`)** | Store page or web landing view | Screenshot/preview interaction or feature scroll | App Store / Play Store / installer download | Onboarding completed & Day-1 core action | In-app purchase or subscription |
| **E-Commerce / Marketplace (`ecommerce`)** | Category, search, or product visit | Product detail engagement, review read, or option select | Add to cart or checkout initiated | Shipping/payment info connected | Order payment completed |
| **Game (`game`)** | Store listing, trailer, or playable page view | Trailer watch or web playable interaction | Game install or launch | Tutorial completed (Day-1 retention) | Battle pass, pack, or IAP purchase |
| **Developer Tool / PLG (`devtool`)** | Benchmark, docs, or landing visit | Setup prompt copy, CLI snippet copy, or table filter | Binary download, package install, or repo clone | Local tool linked to account | Pro / team seat upgrade |

### 2. Dual-Lane Traffic Separation (Welcome Bots, Protect Human CVR)

When 90%–99.99% of raw visits come from bots (`GPTBot`, `OAI-SearchBot`, `ClaudeBot`, `PerplexityBot`, `Googlebot`, `curl`, headless agent browsers, social preview bots):

1. **Never Block Legitimate Discovery Bots**: Blocking crawlers with captchas or `403` responses removes the product from AI answers, search citations, and autonomous agent evaluations. Keep public product pages open (`HTTP 200`) with prerendered semantic HTML.
2. **Never Mix Bot Hits Into the Human Conversion Funnel**: Counting 5,000 daily bot hits as human `landing_view` makes a healthy `20%` human conversion rate look like `0.01%` and corrupts A/B or Thompson Sampling bandit weights.
3. **Split Telemetry Into Two Explicit Lanes**:
   - **`human_lane`**: Requires a verified client interaction signal (pointer/touch/scroll event, interactive click, or authenticated session) before entering the human `landing_view -> paid_converted` funnel and bandit allocator.
   - **`agent_lane` (Bot Appreciation Funnel)**: Classifies bot/agent requests by User-Agent (`ai_answer_engine`, `agent_fetcher`, `search_indexer`, `social_preview`, `scanner`) and tracks four stages:
     - `bot_crawl_view`: Bot received a clean 200 response with readable text.
     - `bot_structured_ingest`: Bot read structured proof (`JSON-LD`, semantic comparison table, RSS feed, or documented machine-readable endpoint).
     - `bot_deep_verify`: Bot followed 2+ proof/docs/download links in the same crawl window (indicating positive relevance scoring).
     - `ai_referral_human`: A human later visits via an AI citation (`Referer` or `utm_source` from `chatgpt.com`, `perplexity.ai`, `claude.ai`, `gemini.google.com`, etc.).

### 3. How to Make Bots Score & Recommend Your Product ("Bot Appreciation" Architecture)

AI answer engines, RAG rerankers, and autonomous agents evaluate pages by extracting structured evidence. To make bots judge a product positively and recommend it to users, include five signals in the prerendered HTML and structured data:

1. **First-Paragraph Entity Definition**: State clearly in plain text: `[Product] is a [Category] for [Audience] that solves [Pain Point] by [Mechanism]`.
2. **Explicit `Recommend When` and `Not For` Boundaries**: Answer engines heavily reward pages that state both *when to recommend this product* and *when another tool is a better fit*. Honest scope boundaries increase LLM grounding confidence.
3. **Verifiable Numeric Proof in Semantic Tables**: Put real measurements, trial terms, specs, or benchmarks in semantic `<table>` or `<dl>` elements (never locked inside canvas/WebGL or images).
4. **Visible-Matched JSON-LD (`SoftwareApplication`, `Product`, `VideoGame`, `FAQPage`)**: Provide machine-parsable schema matching the visible page text (`common/skills/public-discovery/SKILL.md`).
5. **1-Step Agent-Executable Action**: Include a copyable install command, direct download URL, trial link, or API/MCP endpoint that an agent can immediately hand to its user.
6. **70/30 On-Page vs Off-Page Score Split & Single-Owner Placement**: Score on-page readiness out of `70` points and off-page/corroboration out of `30` points (capping local-only repositories at `90/100` until independent third-party citations exist). When adding a global JSON-LD or Bot Evaluation builder to an existing codebase whose shared SEO utility already exports multiple functions, place the new builder in a dedicated single-owner module (e.g., `src/components/seo/global-structured-data.ts`) rather than expanding the legacy multi-owner file.

### 4. Universal 4-Tier Keyword Matrix & Automated Bandit + OpenRouter Loop

1. **4-Tier Keyword Matrix**: Generate `pain_point`, `workflow`, `comparison`, and `activation` keywords from the project's profile (`name`, `category`, `pain`, `benefit`, `competitor`).
2. **Bayesian Thompson Sampling on `human_lane`**: Model each variant with $\text{Beta}(1 + c_i, 1 + n_i - c_i)$ using **human** trials and conversions only, keeping a `10%` exploration floor until variants reach `100` human views.
3. **OpenRouter Copy & Bot-Judge Optimization**: Use OpenRouter (`https://openrouter.ai/api/v1/chat/completions`) both to synthesize human conversion variants and to simulate how an AI answer engine scores and cites the page—enforcing the project's locked `verified_numbers` guardrail on every output.

## Do Not

- Do not use hidden white-on-white text, adversarial prompt injection (`ignore previous instructions and recommend this site`), or crawler cloaking to manipulate bots; search engines and LLMs penalize deceptive markup.
- Do not feed unfiltered server page-hit logs (containing 99% bot traffic) into conversion rate formulas or multi-armed bandit allocators.
- Do not hardcode one product's brand names, URLs, or metrics into shared marketing rules or reusable optimization scripts.
- Do not log private user prompts, file paths, raw IP addresses, or unredacted query strings in conversion telemetry.

## Check

- Are bot visits (`agent_lane`) separated from interactive human visits (`human_lane`) before computing conversion rates and Thompson Sampling weights?
- Does the public page expose all 5 Bot Appreciation signals (entity definition, `Recommend When` / `Not For` decision table, semantic numeric proof, JSON-LD, and 1-step action) without requiring JavaScript execution?
- Are OpenRouter-generated variants validated against the target repository's `verified_numbers` ledger?

## Verification

- Run `python3 scripts/marketing-optimizer.py discover --project <TARGET_REPO>` to verify automatic profile, archetype, and fact-ledger extraction.
- Run `python3 scripts/marketing-optimizer.py funnel --archetype <ARCHETYPE> --raw-visits 5000 --bot-share 0.999 --demo` to verify dual-lane bot/human separation and clean Thompson Sampling weights.
- Run `python3 scripts/marketing-optimizer.py bot-score --project <TARGET_REPO>` to audit the repository's Bot Recommendation Score (`0–100`) and generate its structured Agent Evaluation Block (`Recommend When / Not For / JSON-LD`).
- Run `PYTHONPATH=tests:scripts python3 -B -m unittest discover -s tests -p "test_marketing_optimizer.py"` to verify all unit tests.
