---
keyflow_id: sys_moru_core_readme_zh_cn
status: review
type: human-reviewed-needed
---

# Moru Core

[简体中文](README.zh-CN.md) · [English](README.md) · [한국어](README.ko.md) · [日本語](README.ja.md)

Moru Core 是面向 AI 编程代理（Coding Agents）的共享指南与可执行运行时契约层。只需一次检出（checkout），即可让 Claude Code、Codex、Antigravity 等代理在所有关联仓库中共用相同的操作规则、工作路由（route）、代码审查检查、平台规范以及可验证的生命周期证据（JSON）。各仓库自身的指令保持精简，发生冲突时始终以目标仓库指令为准。

- 代码仓库: <https://github.com/taehwandev/moru-core>
- 官方网站: <https://getmoru.com/core> · [Token 效率与代理架构对比报告](https://getmoru.com/report)
- 版本发布: <https://github.com/taehwandev/moru-core/releases> · 发布说明位于 [`.github/release-notes/`](.github/release-notes/)

代理实际遵循的权威规范为 [AGENTS.md](AGENTS.md) 与英文公共指南。本文档为面向开发者的简体中文说明。

## 核心特性

- **运行时无关（Provider-neutral）**：同一套规则同时适用于 Claude、Codex、Antigravity/AGY；各运行时配置文件仅保留极薄的桥接块。
- **按需读取（Need-Driven Reading）**：每次任务仅加载当前路由要求的必读文档（`required_docs`），绝不全量加载整个规则库。
- **可执行证据（Executable Evidence）**：启动器将路由、门禁（gates）、代码审查与 `finish` 记录为本地 JSON 证据，把“我已经检查过了”的口头声明转化为可机器校验的事实。
- 项目专属的构建命令、路径、产品策略与凭证保存在目标仓库中，绝不放入本仓库。
- 安全扫描由 [VibeGuard](https://vibeguard.thdev.app/) 负责，Moru Core 作为其规则源使用。

运行时标识：启动器 `~/.moru/bin/moru-hook`、环境变量 `MORU_*`、文档占位符 `<MORU_ROOT>`/`<MORU_LAUNCHER>`、本地状态目录 `.moru`、子代理角色 `moru_explorer`/`moru_worker`/`moru_reviewer`。

## 为什么选择 Moru Core（架构对比与 5 个月实测遥测）

![Moru Core v2 5-Month Field Telemetry & Architecture Comparison](docs/assets/moru-core-telemetry.svg)

原生编程 CLI、按需技能包（如 `Superpowers` 或 Claude Agent Skills）以及自演进独立运行时（如 Nous Research 的 Hermes Agent 或 OpenHands）各自解决代理栈不同层面的问题。Moru Core 不是替代现有 CLI 的独立运行时，也不是静态提示词合集，而是**在宿主 CLI 内部管控“按路由读取哪些必读文档”、“如何经校验地演进规则与记忆”以及“满足哪些可执行证据后才允许宣告完成（Done）”的仓库级操作契约**。

| 对比维度 | 原生 CLI (Stock Claude Code / Codex) | 规则集与技能包 (大型 `CLAUDE.md` / `Superpowers`) | 自演进代理运行时 (如 Hermes Agent) | **Moru Core (宿主原生仓库契约)** |
| --- | --- | --- | --- | --- |
| **代理循环所有权** | ✓ 宿主 CLI（原生权限模式、plan/read-only 沙箱、钩子扩展点） | △ 宿主 CLI（常驻巨型 `CLAUDE.md` 或 `SessionStart` 引导技能注入） | △ 独立运行时循环（接管编排、子代理委派、终端后端与网关） | **✓ 宿主 CLI 层**：保留原有的 Claude Code、Codex 或 Antigravity 会话，直接绑定共享仓库契约 |
| **初始上下文与指南选择** | △ 仅加载仓库基础指令；构建与测试规范靠会话中临时探索 | ✕ 巨型单文件每轮支付全量 Prefix 成本（△ 技能包通过工具调用按需加载正文） | ✓ 固定内存快照（`MEMORY.md`+`USER.md` 约 `1.3K` tok）+ 技能索引（约 `3K` tok）+ 按需 FTS5 会话检索 | **✓ 确定性路由清单**：仅绑定当前 route 的 `required_docs`（10 月均值 `4.15` 篇，较 7 月 `20.45` 篇下降 **-79.7%**）；参考文档仅在存在未决决策时打开 |
| **只读提问** *(“为什么只有这个 API 慢？”)* | △ 支持手动 plan/read-only 模式，但未与修改类工作流自动分离 | ✕ 即使只读提问也会加载提交/发布规则或引导指令 | △ 携带启动快照与技能索引在常规代理对话循环中执行 | **✓ 无状态 Read-Only Fast Path**：跳过 `start`/`review`/`finish` 钩子与 worktree 创建，4 跳内直接依据源码作答（活跃只读运行期间自动拦截文件写入） |
| **技能与记忆演进治理** | ✕ 依赖手动编辑 `CLAUDE.md` / `AGENTS.md` 或本地笔记 | ✕ 以人工编写的静态 Markdown 为主，无自动校验或过期（TTL）元数据 | △ 任务后通过 `skill_manage` 自主创建/修补技能（默认 `write_approval: false`，无过期时间）+ 持久 `MEMORY.md` | **✓ 受控演进**：仅在确认 `reusable_gap` 时更新公共规则并通过 `workflow.py validate` 校验；`project-memory` 最多召回 3 条带必填 `--review-on` 过期日与适用条件的记录 |
| **后续跟进（Follow-up）与验证继承** | ✕ 仅靠对话上下文，跨运行无结构化门禁台账 | ✕ 提示词检查清单模式，跟进请求需重复检查或依赖对话记忆 | ✕ FTS5 可检索历史对话，但无绑定文件字节哈希的验证继承台账 | **✓ `--continue-from` & `--reuse-inputs`**：当声明的 `input_paths` 字节哈希及范围/工具链未变时，自动继承已通过的本地测试门禁（10 月连续运行事件中位数 **-54.4%**） |
| **“完成（Done）”判定标准与边界** | ✕ 除非按仓库自建钩子，否则依赖模型自我报告完成 | △ 依赖提示词检查清单（如 `verification-before-completion`），长上下文易漂移 | △ 提供沙箱、消息网关、定时任务与自主技能，但完成判定仍依赖模型判断 | **✓ 可执行 `finish` 硬门禁**：强制校验最新测试证据、开发文件新增 `≤300` 行预算及 VibeGuard（Claude Code 为钩子强制，其余运行时为 CLI 契约校验）。*注：不提供沙箱、聊天网关或免审自主技能生成* |

### 2026 年 5 月–10 月生产环境群组观测记录（单操作员 · 26 个仓库 · 4,984 次 Git 提交 · 419,857 条 Spill 事件）

以下数据汇总自 2026 年 5 月至 10 月的真实开发遥测（`419,857` 条 Spill 记录事件、`1,207` 个 Codex 线程、`584` 次 Moru 追踪运行及 10 月 `265` 次会话绑定运行，覆盖 `26` 个仓库），用于展示工作流演进前后的观测群组变化，而非针对外部运行时的随机对照基准测试：

- **单次运行必读文档（`required_docs`）-79.7%**（7 月 v1 全量清单 `20.45` 篇 → 9 月 `4.29` 篇 → 10 月 Need-Driven Reading `4.15` 篇）。
- **每次 Git 提交记录事件数 -60.7%**（`150.7` 次 → `59.2` 次），**日均提交率 +122.4%**（7 月 11 个活跃仓库日均 `29.5` 次［每仓库 `2.68` 次/日］→ 10 月 17 个活跃仓库日均 `65.6` 次［每仓库 `3.86` 次/日，**单活跃仓库 +44.0%**］）。
- **每个变更文件的参考加权 Token -78.1%**（按 Spill `1.0 / 1.25 / 0.1 / 1.0` 比较指数计算，7 月 `432.5K` → 10 月 `94.6K`；每次提交加权 Token 从 7 月 `3.07M` → 9 月 `1.47M` → 10 月受多文件重构［平均 `17.2` 个文件/提交］影响为 `1.63M`［**较 7 月 -46.9%**］）。
- **Codex 线程 Token 中位数（p50）-93.8%**（`20.28M` → `1.25M`，前 10% 长尾 `p90` 从 `146.1M` 降至 `17.9M`）。
- **同模型内部观测群组对比（固定模型 ID）**：
  - 在 `claude-opus-5-5` 同模型下（9 月 → 10 月），单次运行记录事件中位数从 **`591.0 → 35.5`（-94.0%）**，加权 Token 中位数从 **`33.47M → 0.41M`（-98.8%）**，单事件平均上下文从 **`488.3K → 301.0K`（-38.4%）**。
  - 在 `gpt-6-sol` 同模型下（9 月 → 10 月），单次运行记录事件中位数从 **`855.0 → 174.5`（-79.6%）**，`classify` 阶段事件从 **`1,215.2 → 6.0`（-99.5%）**。
  - 在 2026 年 10 月内部（`265` 次会话绑定运行，匹配覆盖率 `92.98%`），延续运行（`continuation`）相比全新运行（`fresh`）在 `claude-opus-5-5` 上事件中位数降低 **-54.4%（`45.0 → 20.5`）**，在 `commit` 路由上降低 **-75.2%（`52.5 → 13.0` 次，加权 Token `2.02M → 0.29M`，-85.6%）**。

随时在本地查询各项目、群组及月/周效率趋势（传入 `--month` 时按 `W1–W4` 汇总，不导出提示词或文件路径的 Content-Free JSON）：

```bash
python3 scripts/agent-os-status.py --efficiency-trends --all-projects --month 2026-10
```

4 大开发场景架构对比与 5 个月完整台账请见：<https://getmoru.com/report>。

## 快速开始

如果本机已有检出副本或仓库已固定子模块，请直接复用；下载新副本前应先征求用户同意。

```bash
git clone https://github.com/taehwandev/moru-core.git ~/.moru/core   # 个人共享安装
python3 ~/.moru/core/scripts/setup-agent-hooks.py                     # 安装启动器与运行时桥接
<MORU_LAUNCHER> workflow validate
<MORU_LAUNCHER> doctor --project <目标仓库>                            # 只读健康检查
```

团队若需固定版本，可在获得仓库维护者批准后将其添加为 Git 子模块：

```bash
git submodule add https://github.com/taehwandev/moru-core.git .agents/moru-core
```

更新应在任务间隙通过 `git pull --ff-only` 与 `workflow validate` 进行，切勿在任务运行中途更新规则。

## 接入目标项目

1. 先阅读目标仓库现有的 `AGENTS.md`、`CLAUDE.md`、`CODEX.md` 等指令文件。
2. 将 [`templates/repo-agents-routing.md`](templates/repo-agents-routing.md) 中的托管路由块添加到运行时读取的入口文件（优先 `AGENTS.md`）。
3. 提交到仓库的指令应保持可移植：使用 `<MORU_ROOT>`、`${MORU_HOME}` 或 `.agents/moru-core`，不要硬编码个人绝对路径。
4. 将 Moru Core 根目录作为 VibeGuard 规则源执行安全检查：

```bash
npx --yes @taehwandev/vibeguard@latest audit . --rules <MORU_ROOT>
```

可直接粘贴给任何 AI 代理的接入请求模板见 [`templates/apply-moru-request.md`](templates/apply-moru-request.md) 及英文版 [Apply With Any AI Agent](README.md#apply-with-any-ai-agent)。

## 任务执行流程

只读提问直接依据源码证据回答，不启动生命周期。涉及修改的任务通过启动器运行一次：

```bash
<MORU_LAUNCHER> start --project <目标仓库> --rules <MORU_ROOT> \
  --command <route> --request "<用户请求>" \
  --intent <简短分类名> --target-summary "<有界目标摘要>"
```

1. **`start`** 对请求进行分类，选定 route 并绑定权限范围。
2. 阅读该 route 列出的所有 **`required_docs`**。
3. 执行任务并通过 **`gate-batch`** 记录门禁证据；随时运行 `<MORU_LAUNCHER> next` 查看下一步与可复制命令。
4. 运行 **`review`** 检查差异、文件结构、链接与 VibeGuard，并在最终汇报或提交前运行 **`finish`** 校验完整证据链。

门禁状态仅使用 `🐱🟢 SUCCESS` 与 `🐱🔴 FAIL`。中断恢复或后续跟进使用 `start --continue-from <run id>`。经确认的项目事实保存在 `project-memory`，未完成任务保存在 `work-cards`（详见 [docs/project-memory.md](docs/project-memory.md)）。
