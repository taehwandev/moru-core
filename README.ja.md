---
keyflow_id: sys_moru_core_readme_ja
status: review
type: human-reviewed-needed
---

# Moru Core (モル・コア)

[日本語](README.ja.md) · [English](README.md) · [한국어](README.ko.md) · [简体中文](README.zh-CN.md)

Moru Coreは、AIコーディングエージェントのための共有ガイダンスおよび実行契約レイヤーです。1つのチェックアウトをリンクするだけで、Claude Code、Codex、Antigravityなどのエージェントがすべてのリポジトリで同じ運用ルール、作業ルート（route）、レビュー検査、プラットフォーム指針、実行可能なライフサイクル証跡（JSON）を共有します。各リポジトリ固有の指示は最小限に保たれ、競合時はリポジトリ側の指示が優先されます。

- リポジトリ: <https://github.com/taehwandev/moru-core>
- ウェブサイト: <https://getmoru.com/core> · [トークン効率＆エージェント比較レポート](https://getmoru.com/report)
- リリース: <https://github.com/taehwandev/moru-core/releases> · リリースノートは [`.github/release-notes/`](.github/release-notes/)

エージェントが従う正式な基準は [AGENTS.md](AGENTS.md) および英語の共通ドキュメントです。本ドキュメントは人間向けの日本語ガイドです。

## 特徴

- **ランタイム中立**: 同じルールがClaude、Codex、Antigravity/AGYで動作し、各ランタイムの設定ファイルには薄いブリッジブロックだけを配置します。
- **Need-Driven Reading（必要な文書のみ選択）**: タスクごとに確定したrouteが要求する `required_docs` だけを読み込み、ライブラリ全体を一括ロードしません。
- **実行可能な完了証跡（Executable Evidence）**: ランチャーがルーティング、ゲート、レビュー、`finish` をローカルJSON証跡として記録し、「確認しました」という自己申告を機械検証可能な事実に変えます。
- プロジェクト固有のコマンド、パス、製品ポリシー、認証情報は各対象リポジトリに置き、ここには含めません。
- セキュリティ・安全性監査は [VibeGuard](https://vibeguard.thdev.app/) が担当し、Moru Coreはそのルールソースとして機能します。

ランタイム識別子: ランチャー `~/.moru/bin/moru-hook`、環境変数 `MORU_*`、コミット文書内のプレースホルダー `<MORU_ROOT>`/`<MORU_LAUNCHER>`、ローカル状態 `.moru`、エージェントロール `moru_explorer`/`moru_worker`/`moru_reviewer`。

## なぜ Moru Core なのか（アーキテクチャ比較＆5ヶ月間の実測テレメトリ）

![Moru Core v2 5-Month Field Telemetry & Architecture Comparison](docs/assets/moru-core-telemetry.svg)

ネイティブコーディングCLI、オンデマンドスキルパック（`Superpowers` や Claude Agent Skillsなど）、自己進化型スタンドアロンランタイム（Nous Researchの Hermes Agent や OpenHandsなど）は、それぞれ異なるレイヤーの課題を解決します。Moru Coreは既存のCLIを置き換える別ランタイムでも静的なプロンプト集でもなく、**ホストCLIの内部で「どの必須文書を読むか」「ルールとメモリをどう検証して進化させるか」「どの実行証跡が揃ったときに完了（Done）を認めるか」を統制するリポジトリ運用契約**です。

| 比較項目 | ネイティブ CLI (標準 Claude Code / Codex) | ルールブック＆スキルパック (巨大 `CLAUDE.md` / `Superpowers`) | 自己進化型エージェントランタイム (例: Hermes Agent) | **Moru Core (ホストネイティブ・リポジトリ契約)** |
| --- | --- | --- | --- | --- |
| **ループの所有権** | ✓ ホストCLI（標準権限モード、plan/read-onlyサンドボックス、フック拡張） | △ ホストCLI（巨大 `CLAUDE.md` の常時注入、または `SessionStart` ブートストラップ注入） | △ 独立ランタイム（独自のオーケストレーション、サブエージェント、ゲートウェイを所有） | **✓ ホストCLIレイヤー**: 使い慣れたClaude Code・Codex・Antigravityを維持したまま共通リポジトリ契約を結合 |
| **初期コンテキスト＆指針選択** | △ リポジトリの基本指示のみロード。ビルド・テスト規約はセッション中に探索 | ✕ 巨大単一ファイルは毎ターンPrefixコストを消費（△ スキルパックはツール呼び出しでオンデマンド読込） | ✓ 固定メモリスナップショット（`MEMORY.md`+`USER.md` 約 `1.3K` tok）＋スキルインデックス（約 `3K` tok）＋オンデマンドFTS5検索 | **✓ 決定論的ルートマニフェスト**: 確定したrouteの `required_docs` のみ選択（10月平均 `4.15` 件、7月 `20.45` 件比 **-79.7%**）。未解決の判断時のみ参照文書をロード |
| **読み取り専用の質問** *(「なぜこのAPIだけ遅い？」)* | △ 手動plan/read-onlyモードはあるが通常ワークフローと自動分離されない | ✕ 質問だけでもコミット・リリース規則やブートストラップ指針が注入される | △ 固定スナップショットを伴い通常のエージェント会話ループ内で実行 | **✓ ステートレス Read-Only Fast Path**: `start`/`review`/`finish` フックとworktree生成を完全スキップし4ホップ以内の直接根拠で即答（読み取り専用ラン中は書込遮断） |
| **スキル・メモリの学習とガバナンス** | ✕ `CLAUDE.md` / `AGENTS.md` の手動編集またはローカルメモに依存 | ✕ 人間が書く静的Markdown中心で自動検証や有効期限（TTL）メタデータなし | △ タスク後に `skill_manage` でスキルを自律生成・パッチ（デフォルト `write_approval: false`、有効期限なし）＋永続 `MEMORY.md` | **✓ 検証された進化**: 検証済み `reusable_gap` 発生時のみ共通ルールを更新し `workflow.py validate` で検証。`project-memory` は `--review-on` 期限と適用条件付きの最大3件のみ想起 |
| **後続作業（Follow-up）と再検証の継承** | ✕ 会話文脈のみでラン間の構造化された検証ゲート台帳がない | ✕ プロンプト内のチェックリスト方式のため後続要求時に再実行または会話記憶に依存 | ✕ FTS5検索で過去の会話は引けるが、ファイルバイトハッシュに紐づく検証台帳はない | **✓ `--continue-from` & `--reuse-inputs`**: 宣言された `input_paths` ハッシュとスコープ・ツールチェーンが一致すれば通過済みローカルゲートを自動継承（10月連続ラン中央値 **-54.4%**） |
| **「完了（Done）」判定基準と役割境界** | ✕ カスタムフックを自作しない限りモデルの自己申告で完了 | △ プロンプトによるチェックリスト勧告（長文コンテキストで形骸化しやすい） | △ サンドボックス・メッセンジャー・cron・自律スキルを備えるが完了判定はモデル判断に依存 | **✓ 実行型 `finish` ハードゲート**: 最新テスト証跡・開発ファイル追加 `300行` 予算・VibeGuard通過を検証（Claude Codeはフック強制、他はCLI契約検証）。*※サンドボックスやチャットゲートウェイ等は提供しない* |

### 2026年5月〜10月 フィールドコホート観測記録（単一オペレーター・26リポジトリ・4,984 Gitコミット・419,857 Spillイベント）

以下の数値は2026年5月〜10月の自社開発テレメトリ（`419,857` Spill記録イベント、`1,207` Codexスレッド、`584` Moru追跡ラン、10月のセッション結合 `265` ラン）におけるワークフロー進化前後の観測コホート比較であり、外部ランタイムとの統制ベンチマークではありません。

- **ランあたり必須文書（`required_docs`）-79.7%**（7月v1の `20.45` 件 → 9月 `4.29` 件 → 10月 `4.15` 件、Need-Driven Reading）。
- **Gitコミット1件あたり記録イベント -60.7%**（`150.7` 回 → `59.2` 回）および **1日あたりコミット数 +122.4%**（7月11アクティブrepoで `29.5件/日`［`2.68/repo`］→ 10月17アクティブrepoで `65.6件/日`［`3.86/repo`、**アクティブrepoあたり +44.0%**］）。
- **変更ファイル1件あたり参照加重トークン -78.1%**（Spill `1.0 / 1.25 / 0.1 / 1.0` 比較指数で7月 `432.5K` → 10月 `94.6K`。コミットあたり加重トークンは7月 `3.07M` → 9月 `1.47M` → 10月はマルチファイル改修［平均 `17.2` ファイル/コミット］の影響で `1.63M`［**7月比 -46.9%**］）。
- **Codexスレッドトークン中央値（p50）-93.8%**（`20.28M` → `1.25M`、上位10% `p90` は `146.1M` → `17.9M`）。
- **同一モデル内コホート比較（モデルID固定）**:
  - `claude-opus-5-5` 同一モデル（9月 → 10月）で、ランあたり記録イベント中央値が **`591.0回 → 35.5回`（-94.0%）**、加重トークン中央値が **`33.47M → 0.41M`（-98.8%）**、イベントあたり平均コンテキストが **`488.3K → 301.0K`（-38.4%）** に減少。
  - `gpt-6-sol` 同一モデル（9月 → 10月）で、ランあたり記録イベント中央値が **`855.0回 → 174.5回`（-79.6%）**、`classify` 段階イベントが **`1,215.2回 → 6.0回`（-99.5%）** に減少。
  - 2026年10月（`265` セッション結合ラン、マッチ率 `92.98%`）内でも、連続ラン（`continuation`）は新規ラン（`fresh`）に比べ `claude-opus-5-5` イベント中央値が **`45.0回 → 20.5回`（-54.4%）**、`commit` ルートでは **`52.5回 → 13.0回`（-75.2%、加重トークン `2.02M → 0.29M`、-85.6%）** に短縮。

ローカルの効率トレンド（`--month` 指定時は `W1〜W4` 週次集計、プロンプトやファイルパスを含まないContent-Free JSON）は以下のコマンドで確認できます：

```bash
python3 scripts/agent-os-status.py --efficiency-trends --all-projects --month 2026-10
```

4つの作業シナリオ別比較と5ヶ月間の全月次台帳は <https://getmoru.com/report> で確認できます。

## クイックスタート

マシン上に既存のチェックアウトやチーム固定のコピーがある場合はそれを再利用します。新しくクローンする前に必ずユーザーに確認します。

```bash
git clone https://github.com/taehwandev/moru-core.git ~/.moru/core   # 個人共有インストール
python3 ~/.moru/core/scripts/setup-agent-hooks.py                     # ランチャー＆ランタイムブリッジ設定
<MORU_LAUNCHER> workflow validate
<MORU_LAUNCHER> doctor --project <対象リポジトリ>                      # 読み取り専用ヘルスチェック
```

チームでバージョンを固定する場合は、リポジトリ管理者の承認を得てサブモジュールとして追加します：

```bash
git submodule add https://github.com/taehwandev/moru-core.git .agents/moru-core
```

更新は実行中のタスクが完了した後に `git pull --ff-only` と `workflow validate` で行います。

## プロジェクトへの接続

1. 対象リポジトリの既存の `AGENTS.md`、`CLAUDE.md`、`CODEX.md` などの指示を先に読みます。
2. [`templates/repo-agents-routing.md`](templates/repo-agents-routing.md) のルーティングブロックをランタイムが読むファイル（優先は `AGENTS.md`）に追加します。
3. コミットされる指示ファイルには個人の絶対パスを書かず、`<MORU_ROOT>`、`${MORU_HOME}`、`.agents/moru-core` などのポータブルな表記を使います。
4. VibeGuardにMoru Coreルートをルールソースとして指定します：

```bash
npx --yes @taehwandev/vibeguard@latest audit . --rules <MORU_ROOT>
```

エージェントセッションにそのまま貼り付けられる適用リクエスト文は [`templates/apply-moru-request.md`](templates/apply-moru-request.md) および英語版の [Apply With Any AI Agent](README.md#apply-with-any-ai-agent) を参照してください。

## タスクの実行フロー

読み取り専用の質問はライフサイクルを起動せず直接根拠から即答します。ファイルを変更する作業はランチャーで1回開始します：

```bash
<MORU_LAUNCHER> start --project <対象リポジトリ> --rules <MORU_ROOT> \
  --command <route> --request "<ユーザー要求>" \
  --intent <短い分類名> --target-summary "<作業対象要約>"
```

1. **`start`** が要求を分類し、routeと権限範囲を確定します。
2. routeが指定した **`required_docs`** を読みます。
3. 作業を進めながら **`gate-batch`** でゲート証跡を記録します。`<MORU_LAUNCHER> next` で次のステップとコピー可能なコマンドを確認できます。
4. **`review`** で差分・構造・リンク・VibeGuardを検査し、最終報告やコミットの前に **`finish`** で全証跡を検証します。

ゲート状態は `🐱🟢 SUCCESS` と `🐱🔴 FAIL` の2つのみです。中断した作業や後続フォローアップは `start --continue-from <run id>` で引き継ぎます。検証済みのプロジェクト事実は `project-memory` に、未完了タスクは `work-cards` に記録されます（詳細: [docs/project-memory.md](docs/project-memory.md)）。
