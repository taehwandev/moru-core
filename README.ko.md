---
keyflow_id: sys_moru_core_readme_ko
status: review
type: human-reviewed-needed
---

# 모루 코어 (Moru Core)

[한국어](README.ko.md) · [English](README.md)

모루 코어는 AI 코딩 에이전트가 여러 저장소에서 재사용할 수 있는 작업 지침과 실행 근거 체계입니다. 작업 분류, 필요한 문서 선택, 검토, 검증, 인수인계 규칙을 제공합니다. 프로젝트 고유의 명령과 정책은 각 프로젝트의 지침 파일에 둡니다.

저장소 주소는 <https://github.com/taehwandev/moru-core>이며, 공개 사이트는 현재 <https://tao.thdev.app/>입니다. 상세한 운영·기여 지침은 [영문 README](README.md)와 [AGENTS.md](AGENTS.md)에 있습니다.

## 사용 대상과 구성

- 여러 프로젝트에서 AI 에이전트를 사용하는 개인과 팀
- 긴 지침을 각 저장소에 복사하지 않고 공통 기준을 유지하려는 관리자
- 저장소별 규칙을 우선하면서 공통 작업 절차와 검증 근거를 재사용하려는 도구 개발자

`AGENTS.md`는 공통 진입점, `common/`은 일반 엔지니어링 규칙, `platforms/`는 플랫폼별 지침, `product-patterns/`는 제품 패턴, `workflows/`는 작업 절차, `scripts/`는 실행 도구, `templates/`는 연결용 예시입니다. 필요한 문서만 선택해 읽습니다.

## 시작하기

기존 설치나 팀에서 고정한 복사본이 있다면 해당 경로를 재사용합니다. 새 복사본을 만들기 전에 현재 설치 위치와 프로젝트의 `AGENTS.md` 등 지침을 확인하세요.

처음 설치하는 개인 환경의 예시는 다음과 같습니다. 전환 기간에는 `MORU_HOME`이 호환 환경변수이고, `<MORU_LAUNCHER>`는 설치된 런처의 절대 경로를 뜻합니다.

```bash
export MORU_HOME="$HOME/.moru/core"
git clone https://github.com/taehwandev/moru-core.git "$MORU_HOME"
python3 "$MORU_HOME/scripts/workflow.py" validate
```

팀에서 버전을 고정하려면 대상 저장소의 승인과 업데이트 정책에 따라 서브모듈 등의 방식으로 `.agents/moru-core`에 연결할 수 있습니다. 개인 절대 경로를 커밋되는 프로젝트 지침에 넣지 마세요.

```bash
git submodule add https://github.com/taehwandev/moru-core.git .agents/moru-core
```

설치본을 갱신할 때는 진행 중인 에이전트 작업이 끝난 뒤 선택한 체크아웃에서 `git pull --ff-only`를 실행하고, 런처의 `workflow validate`와 VibeGuard 검사를 수행합니다. 자세한 절차는 [기존 설치 최신화 안내](docs/ko/update-moru.md)를 참고하세요.

## 프로젝트에 연결하기

1. 대상 프로젝트의 `AGENTS.md`, `CLAUDE.md`, `CODEX.md` 등 현재 지침을 먼저 읽습니다.
2. 기존 모루 코어 설치를 재사용하거나, 설치가 없다면 설치 위치를 정합니다.
3. 프로젝트 지침 파일에 모루 코어의 짧은 포인터를 추가합니다. 프로젝트 전용 명령·경로·제품 정책은 그 프로젝트에 남깁니다.
4. VibeGuard에서 선택한 모루 코어 루트를 규칙 소스로 지정합니다. 기존 설정이 있으면 덮어쓰기 전에 적용 방법을 결정합니다.
5. 여러 단계 작업은 설치된 런처의 `start`로 한 번 시작하고, 반환된 필수 문서와 게이트를 따릅니다. 의미 있는 변경은 `review`, 완료 전에는 `finish`로 확인합니다.

영문 [적용 예시](README.md#apply-with-any-ai-agent)와 [연결 템플릿](templates/repo-agents-routing.md)에 명령과 포인터 형식이 있습니다.

## 이름과 기록 경로 전환

저장소 이름은 `moru-core`입니다. `.moru-core`라는 기록 폴더를 사용하지 않습니다. 런타임 식별자는 Moru 이름을 씁니다: `~/.moru/bin/moru-hook` 런처, `MORU_*` 설정, `<MORU_ROOT>`/`<MORU_LAUNCHER>` 표기, `.moru` 기록, `moru_*` 에이전트 역할입니다. 새 설치와 새 프로젝트는 처음부터 이 이름을 사용합니다.

공개 사이트 주소 `tao.thdev.app`은 새 도메인 연결 전까지 그대로 사용합니다.

## 문서 언어와 기준

이 문서는 공개용 한국어 안내입니다. 에이전트가 따라야 할 규칙은 [AGENTS.md](AGENTS.md)와 영문 공통 지침이 기준입니다. 릴리스 정보는 [GitHub Releases](https://github.com/taehwandev/moru-core/releases)에서 확인하세요.
