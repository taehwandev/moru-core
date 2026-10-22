---
keyflow_id: sys_moru_core_readme_ko
status: review
type: human-reviewed-needed
---

# 모루 코어 (Moru Core)

[한국어](README.ko.md) · [English](README.md) · [日本語](README.ja.md) · [简体中文](README.zh-CN.md)

모루 코어는 AI 코딩 에이전트를 위한 공통 지침이자 실행 계층입니다. 체크아웃 하나만 있으면 연결한 모든 저장소에서 Claude, Codex, Antigravity 같은 에이전트가 같은 작업 규칙, 작업 경로(route), 리뷰 검사, 플랫폼 지침, 실행 근거를 씁니다. 저장소별 지침은 짧게 유지되고, 충돌하면 저장소 지침이 우선합니다.

- 저장소: <https://github.com/taehwandev/moru-core>
- 사이트: <https://getmoru.com/core> · [토큰 효율 및 에이전트 비교 리포트](https://getmoru.com/report)
- 릴리스: <https://github.com/taehwandev/moru-core/releases> · 릴리스 노트는 [`.github/release-notes/`](.github/release-notes/)

에이전트가 따르는 기준은 [AGENTS.md](AGENTS.md)와 영문 공통 지침입니다. 이 문서는 사람을 위한 한국어 안내입니다.

## 무엇인가

- **런타임 중립**: 같은 규칙이 Claude, Codex, Antigravity/AGY에서 동작하고, 런타임별 파일은 얇은 연결 블록만 둡니다.
- **필요한 것만 읽기**: 작업마다 route가 요구하는 문서만 읽습니다.
- **실행 근거**: 런처가 route, 게이트, 리뷰, 마무리를 로컬 JSON 근거로 남겨서 "확인했다"는 말이 실제 확인 기록이 됩니다.
- 프로젝트 고유의 명령, 경로, 제품 정책, 비밀값은 각 저장소에 둡니다.
- 안전 검사는 [VibeGuard](https://vibeguard.thdev.app/)가 맡고, 모루 코어는 그 규칙 소스로 쓰입니다.

런타임 이름: 런처 `~/.moru/bin/moru-hook`, 설정 `MORU_*`, 커밋되는 문서의 표기 `<MORU_ROOT>`/`<MORU_LAUNCHER>`, 로컬 기록 `.moru`, 에이전트 역할 `moru_explorer`/`moru_worker`/`moru_reviewer`.

## 왜 모루 코어인가 (에이전트 아키텍처 비교 및 현장 텔레메트리)

![Moru Core v2 5-Month Field Telemetry & Architecture Comparison](docs/assets/moru-core-telemetry.svg)

네이티브 코딩 CLI, 온디맨드 스킬 팩(`Superpowers`·Claude Agent Skills 등), 자기 진화형 독립 런타임(Nous Research의 Hermes Agent·OpenHands 등)은 각각 서로 다른 계층의 문제를 풉니다. 모루 코어는 기존 CLI를 대체하는 별도 런타임이나 단순 프롬프트 모음집이 아니라, **호스트 CLI 안에서 어떤 필수 문서를 읽고·어떻게 규칙과 메모리를 검증해 진화시키며·어떤 실행 근거가 확인될 때 완료(Done)를 인정할지 통제하는 저장소 운영 계약**입니다.

| 비교 차원 | 네이티브 CLI (기본 Claude Code / Codex) | 규칙집 및 스킬 팩 (대형 `CLAUDE.md` / `Superpowers`) | 자기 진화형 에이전트 런타임 (예: Hermes Agent) | **Moru Core (호스트 네이티브 저장소 계약)** |
| --- | --- | --- | --- | --- |
| **에이전트 루프 소유권** | 호스트 CLI (기본 권한 모드, plan/read-only 샌드박스, 훅 확장 포인트 제공) | 호스트 CLI (거대 단일 `CLAUDE.md` 상시 주입 또는 `SessionStart` 부트스트랩 스킬 주입) | 독립 에이전트 런타임 (자체 오케스트레이션 루프, 서브에이전트 위임, 터미널 백엔드, 게이트웨이 소유) | **호스트 CLI 계층**: 쓰던 Claude Code·Codex·Antigravity를 유지한 채 저장소 공통 작업 계약을 결합 |
| **초기 컨텍스트 및 지침 선택** | 저장소 기본 지침만 로드하며 빌드·테스트 규칙은 세션 중 탐색 | 대형 단일 `CLAUDE.md`는 매 턴 Prefix 비용을 지불하며, 스킬 팩은 필요 시 `Skill` 도구로 본문 로드 | 상시 메모리 스냅샷(`MEMORY.md`+`USER.md` 약 `1.3K` tok)과 스킬 인덱스(약 `3K` tok)를 고정 주입하고 `skill_view`·FTS5 검색을 온디맨드 호출 | **결정론적 라우트 명세**: 확정된 route의 `required_docs`만 선택(10월 평균 `4.15개`, 7월 자체 `20.45개` 대비 **-79.7%**). 미해결 의사결정에만 참고 문서 추가 로드 |
| **읽기 전용 질문** *(“왜 이 API만 느려?”)* | 수동 plan/read-only 모드를 지원하나 일반 작업 워크플로와 자동 분리되지는 않음 | 단일 거대 규칙집은 리뷰·배포 규칙까지 함께 로드하며, 스킬 팩은 부트스트랩 지침 주입 | 가벼운 고정 스냅샷 및 스킬 인덱스와 함께 일반 대화 루프에서 실행 | **무상태 Read-Only Fast Path**: `start`/`review`/`finish` 라이프사이클과 워크트리 생성을 생략하고 근거 코드만 확인(활성 read-only 런에서는 쓰기 차단) |
| **지침·메모리의 학습과 수명주기** | `CLAUDE.md` / `AGENTS.md` 수동 편집 또는 로컬 메모 | 사람이 작성한 정적 마크다운 스킬 위주이며 자동 검증·만료(TTL) 메타데이터 없음 | 작업 후 에이전트가 `skill_manage`로 스킬을 자동 생성·패치(기본 `write_approval` 비활성, 만료 기한 없음) + 영구 `MEMORY.md` 유지 | **검증된 진화**: 검증된 `reusable_gap` 발생 시에만 공통 규칙을 갱신하고 `workflow.py validate`로 검증. `project-memory`는 `--review-on` 만료일과 `--applies-when`/`--not-when` 조건이 붙은 최대 3건만 호출 |
| **후속 작업(Follow-up) 및 재검증** | 대화 문맥만 유지되며 런 간 구조화된 검증 게이트 원장이 없음 | 프롬프트 체크리스트 방식이라 후속 요청 시 점검을 반복하거나 대화 기억에 의존 | FTS5 세션 검색으로 과거 대화는 찾지만 파일 바이트 해시에 묶인 게이트 승계 원장은 없음 | **`--continue-from` & `--reuse-inputs`**로 선언된 `input_paths` 해시와 범위·툴체인이 유효하면 통과한 로컬 게이트를 자동 승계(10월 관찰 코호트에서 신규 런 대비 연속 런 이벤트 중앙값 **-54.4%**) |
| **‘완료(Done)’ 판정과 역할 경계** | 저장소별 커스텀 훅을 직접 구축하지 않으면 모델의 자체 완료 보고에 의존 | 프롬프트 체크리스트(예: `verification-before-completion`)로 권고하며 강제 원장은 없음 | 샌드박스·메신저·스케줄러·자율 스킬 생성을 제공하는 대신 완료 판정은 모델 판단에 의존 | **실행형 `finish` 게이트**가 최신 테스트 근거·신규/확장 개발 파일 추가 `300줄` 예산·VibeGuard 통과를 확인(Claude Code는 훅 강제, 타 런타임은 CLI 계약 검증). *단, 샌드박스·메신저·크론·비검증 자율 스킬 생성은 제공하지 않음.* |

### 2026년 5월~10월 현장 코호트 관찰 기록 (단일 운영자 · 26개 저장소 · 4,984 Git 커밋 · 419,857 Spill 이벤트)

아래 수치는 2026년 5월~10월 자체 현장 텔레메트리(`419,857` Spill 기록 이벤트, `1,207` Codex 스레드, `584` Moru 트래킹 런, 10월 세션 결합 `265`런)에서 워크플로 진화에 따른 코호트 변화를 집계한 관찰 기록이며, 외부 런타임과의 통제 벤치마크가 아닙니다.

- **런당 라우트 필수 문서(`required_docs`) -79.7%** (7월 초기 명세 `20.45개` → 9월 `4.29개` → 10월 `4.15개`, Need-Driven Reading).
- **Git 커밋 1건당 기록 이벤트 -60.7%** (`150.7회` → `59.2회`) 및 **일평균 커밋 +122.4%** (7월 11개 활성 저장소 일 `29.5건`[저장소당 `2.68건/일`] → 10월 17개 활성 저장소 일 `65.6건`[저장소당 `3.86건/일`, **활성 저장소당 +44.0%**]).
- **변경 파일 1개당 참조 가중 토큰 -78.1%** (Spill `1.0 / 1.25 / 0.1 / 1.0` 비교 지수 기준 7월 `432.5K` → 10월 `94.6K`; 커밋당 가중 토큰은 7월 `3.07M` → 9월 `1.47M` → 10월 다중 파일 리팩터링[커밋당 `17.2개` 파일] 영향으로 `1.63M`[**7월 대비 -46.9%**] 기록).
- **Codex 스레드 토큰 중앙값(p50) -93.8%** (`20.28M` → `1.25M`, 상위 10% `p90`은 `146.1M` → `17.9M`).
- **동일 모델 내 관찰 코호트 비교 (모델 ID 고정)**:
  - `claude-opus-5-5` 동일 모델(9월 → 10월)에서 런당 기록 이벤트 중앙값이 **`591.0회 → 35.5회`(-94.0%)**, 가중 토큰 중앙값이 **`33.47M → 0.41M`(-98.8%)**, 이벤트당 평균 컨텍스트가 **`488.3K → 301.0K`(-38.4%)**로 감소.
  - `gpt-6-sol` 동일 모델(9월 → 10월)에서 런당 기록 이벤트 중앙값이 **`855.0회 → 174.5회`(-79.6%)**, `classify` 단계 이벤트가 **`1,215.2회 → 6.0회`(-99.5%)**로 감소.
  - 2026년 10월(`265개` 세션 결합 런, 매칭 커버리지 `92.98%`) 내에서도 연속 런(`continuation`)이 신규 런(`fresh`) 대비 `claude-opus-5-5` 이벤트 중앙값을 **`45.0회 → 20.5회`(-54.4%)**, `commit` route 이벤트 중앙값을 **`52.5회 → 13.0회`(-75.2%, 가중 토큰 `2.02M → 0.29M`, -85.6%)**로 단축.

로컬에 축적된 프로젝트별·코호트별·월/주차 구간별 토큰 효율 추세(`--month` 지정 시 `W1~W4` 집계)는 아래 명령으로 언제든 조회할 수 있습니다(프롬프트·파일 경로 미포함 Content-Free JSON):

```bash
python3 scripts/agent-os-status.py --efficiency-trends --all-projects --month 2026-10
```

4대 작업 시나리오별 아키텍처 비교와 2026년 5월~10월 전체 원장은 <https://getmoru.com/report> 에서 확인할 수 있습니다.

## 시작하기

이미 설치된 체크아웃이나 팀이 고정한 복사본이 있으면 그것을 재사용합니다. 새로 받기 전에 사용자에게 먼저 묻습니다.

```bash
git clone https://github.com/taehwandev/moru-core.git ~/.moru/core   # 개인 공유 설치
python3 ~/.moru/core/scripts/setup-agent-hooks.py                     # 런처·런타임 연결 설치
<MORU_LAUNCHER> workflow validate
<MORU_LAUNCHER> doctor --project <대상 저장소>                          # 읽기 전용 점검
```

팀이 버전을 고정하려면 저장소 관리자의 승인을 받아 서브모듈로 연결합니다.

```bash
git submodule add https://github.com/taehwandev/moru-core.git .agents/moru-core
```

갱신은 진행 중인 작업이 끝난 뒤 `git pull --ff-only`와 `workflow validate`로 합니다. 자세한 절차는 [기존 설치 최신화 안내](docs/ko/update-moru.md)에 있습니다.

## 프로젝트에 연결하기

1. 대상 저장소의 `AGENTS.md`, `CLAUDE.md`, `CODEX.md` 등 기존 지침을 먼저 읽습니다.
2. [연결 템플릿](templates/repo-agents-routing.md)의 라우팅 블록을 런타임이 읽는 파일(가능하면 `AGENTS.md`)에 넣습니다.
3. 커밋되는 지침에는 개인 절대 경로 대신 `<MORU_ROOT>`, `${MORU_HOME}`, `.agents/moru-core` 같은 경로를 씁니다.
4. VibeGuard에 모루 코어 루트를 규칙 소스로 지정합니다. 기존 설정이 있으면 덮어쓰기 전에 적용 방법을 정합니다.

에이전트에게 붙여 넣을 요청문은 [적용 요청 템플릿](templates/apply-moru-request.md)과 영문 [적용 예시](README.md#apply-with-any-ai-agent)에 있습니다.

## 작업 흐름

읽기만 하는 질문은 근거를 보고 바로 답합니다. 무언가를 바꾸는 작업은 런처로 한 번 시작합니다.

```bash
<MORU_LAUNCHER> start --project <대상 저장소> --rules <MORU_ROOT> \
  --command <route> --request "<사용자 요청>" \
  --intent <짧은_분류명> --target-summary "<작업 대상 요약>"
```

1. `start`가 요청을 분류하고 route와 권한 범위를 정합니다.
2. route가 지정한 `required_docs`를 읽습니다.
3. 작업하면서 게이트를 `gate-batch`로 기록합니다. `<MORU_LAUNCHER> next`가 다음 단계와 바로 쓸 명령을 알려 줍니다.
4. `review`로 변경을 검사하고, 보고·커밋·인수인계 전에 `finish`로 근거를 확인합니다.

게이트 상태는 `🐱🟢 SUCCESS`와 `🐱🔴 FAIL` 두 가지뿐입니다. 멈춘 작업은 `start --continue-from <run id>`로 이어 갑니다. 에이전트가 확인한 프로젝트 사실은 project memory에, 끝나지 않은 작업은 work card에 남습니다([설명](docs/project-memory.md)).

## 저장소 구성

`AGENTS.md`는 공통 진입점, `index.md`는 문서 목록, `common/`은 일반 엔지니어링 규칙, `platforms/`는 플랫폼별 지침, `product-patterns/`는 제품 패턴, `workflows/`는 작업 절차, `scripts/`는 런처와 검사 도구, `templates/`는 연결 블록과 요청문, `docs/`는 참고 문서·명세·런타임 스킬입니다.

릴리스 태그는 주 단위 CalVer `vYY.WW.N`을 씁니다. 한국 달력(Asia/Seoul, 월요일 시작 주차) 기준이고, 주마다 `.0`부터 셉니다.
