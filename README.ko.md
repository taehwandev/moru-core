---
keyflow_id: sys_moru_core_readme_ko
status: review
type: human-reviewed-needed
---

# 모루 코어 (Moru Core)

[한국어](README.ko.md) · [English](README.md)

모루 코어는 AI 코딩 에이전트를 위한 공통 지침이자 실행 계층입니다. 체크아웃 하나만 있으면 연결한 모든 저장소에서 Claude, Codex, Antigravity 같은 에이전트가 같은 작업 규칙, 작업 경로(route), 리뷰 검사, 플랫폼 지침, 실행 근거를 씁니다. 저장소별 지침은 짧게 유지되고, 충돌하면 저장소 지침이 우선합니다.

- 저장소: <https://github.com/taehwandev/moru-core>
- 사이트: <https://tao.thdev.app/> (새 도메인을 연결할 때까지 유지)
- 릴리스: <https://github.com/taehwandev/moru-core/releases> · 릴리스 노트는 [`.github/release-notes/`](.github/release-notes/)

에이전트가 따르는 기준은 [AGENTS.md](AGENTS.md)와 영문 공통 지침입니다. 이 문서는 사람을 위한 한국어 안내입니다.

## 무엇인가

- **런타임 중립**: 같은 규칙이 Claude, Codex, Antigravity/AGY에서 동작하고, 런타임별 파일은 얇은 연결 블록만 둡니다.
- **필요한 것만 읽기**: 작업마다 route가 요구하는 문서만 읽습니다.
- **실행 근거**: 런처가 route, 게이트, 리뷰, 마무리를 로컬 JSON 근거로 남겨서 "확인했다"는 말이 실제 확인 기록이 됩니다.
- 프로젝트 고유의 명령, 경로, 제품 정책, 비밀값은 각 저장소에 둡니다.
- 안전 검사는 [VibeGuard](https://vibeguard.thdev.app/)가 맡고, 모루 코어는 그 규칙 소스로 쓰입니다.

런타임 이름: 런처 `~/.moru/bin/moru-hook`, 설정 `MORU_*`, 커밋되는 문서의 표기 `<MORU_ROOT>`/`<MORU_LAUNCHER>`, 로컬 기록 `.moru`, 에이전트 역할 `moru_explorer`/`moru_worker`/`moru_reviewer`.

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

`AGENTS.md`는 공통 진입점, `index.md`는 문서 목록, `common/`은 일반 엔지니어링 규칙, `platforms/`는 플랫폼별 지침, `product-patterns/`는 제품 패턴, `workflows/`는 작업 절차, `scripts/`는 런처와 검사 도구, `templates/`는 연결 블록과 요청문, `docs/`는 공개 사이트와 참고 문서입니다.

릴리스 태그는 주 단위 CalVer `vYY.WW.N`을 씁니다. 한국 달력(Asia/Seoul, 월요일 시작 주차) 기준이고, 주마다 `.0`부터 셉니다.
