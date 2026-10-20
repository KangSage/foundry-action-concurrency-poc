# AI 코딩 하네스: slop, merge, 설계 잠금, 모름 먼저

> 2026-10-20 · Foundry 에서 AI 코딩 도우미와 일할 때 쓰는 규칙 (PLAN 12~15).
> 이 PoC 의 [docs/design.md](design.md) 처럼 "미지수 먼저, 설계 확정 후 실행" 을 AI 에게 강제하는 방법이다.

AI 가 쓰레기 코드를 남기는 문제, 머지하다 코드를 지어내는 문제, 급할 때 설계를 버리는 문제, 그리고 문서가 흐려서 테스트로 설계를 채우는 문제를 막는다.

## 장치 요약

| 장치 | 무엇 | 막는 것 |
|---|---|---|
| lean-code (12) | 모르면 질문, 요청한 줄만, 새 추상화 금지 | 불필요한 코드, 추측 |
| verify-done (12) | 완료 전 확인 명령 새로 실행, 결과 붙임 | "될 거예요" 거짓 완료 |
| slop.sh (12) | linter 또는 rg 로 console.log, TODO 등 찾으면 exit 1 | md 규칙 무시 |
| safe-merge (13) | 충돌 파일 1개씩, 양쪽 줄만 사용 | 머지하다 코드 지어냄 |
| merge-check.sh (13) | 양쪽 부모에 없던 줄 찾으면 exit 1 | 지어낸 줄이 그대로 들어감 |
| 설계 파일 | 코드 전에 `docs/design/<기능>.md` | 설계가 대화에만 있다가 사라짐 |
| demo 모드 | 테스트만 확인 1개로 줄임. 설계는 그대로 | "빨리" = "규칙 전부 풀기" 로 읽음 |
| 멈추고 질문 | type, property, 매핑 변경, JSON 몰아넣기 전에 질문 | 설계를 몰래 바꿈 |
| design-check.sh | 추가 줄의 JSON 직렬화 찾으면 exit 1 | md 규칙 무시 |
| 거르기 | 틀려도 설계 안 바뀌면 확인 안 함. `## 가정` + `ASSUMPTION:` 주석 | 모든 모름을 다 확인하느라 느림 |
| 모름 먼저 | 모름 목록 → 사실 파일·질문 → probe 1개 → 설계 확정 | PoC 식 테스트 반복 |
| 갈아끼우기 | 가정한 곳은 함수 1개 뒤에 숨김 | 가정 틀렸을 때 전체 재설계 |
| foundry.md | 확인한 Foundry 사실 1줄씩 저장 | 같은 것을 또 테스트 |

## PLAN 12. slop 줄이기

### 왜

md 규칙은 AI 가 무시할 수 있다. 명령(lint, test)은 무시 못 한다. 그래서 규칙 2개(skill)와 검사 명령 1개를 같이 둔다.

### 규칙

- **lean-code** (skill): 모르면 가정 말고 선택지로 질문. 요청한 줄만 고침, 기존 스타일 따름. 안 쓰는 코드, 새 추상화, 새 파일 금지. 표준 library 에 있으면 직접 안 짬. 시작 전 성공기준(확인 명령)을 먼저 씀.
- **verify-done** (skill): "완료, 고침, 통과" 라고 말하기 전에 확인 명령을 새로 실행하고, 출력과 exit code 를 읽고, 결과를 붙여서 말함. "될 거, 아마" 금지.
- **slop.sh**: 컨테이너에 있는 linter 를 `which` 로 찾아 씀 (오프라인이라 설치 금지). 없으면 `rg` 로 `console.log`, 주석 처리된 코드, `TODO`, `any` 타입, 빈 `catch` 를 찾아 경로:줄 출력, exit 1.
- AGENTS.md 1줄: 코드 고칠 땐 lean-code, 끝나면 slop.sh 0 될 때까지, 그 다음 verify-done.

### 과잉 검증 막기

12 의 "확인" 은 테스트를 늘리는 장치가 아니다. 거짓 완료만 막는다.

- 확인 명령은 시작 전에 **1개**만 정한다. 새 테스트 파일은 만들지 않는다.
- verify-done 은 그 1개를 다시 실행할 뿐이다. 테스트 양은 PLAN 14 를 따른다 (demo = 1개, 평소 = 정상 1, 실패 1, 경계 1).
- slop.sh 는 테스트가 아니다. 검색이라 몇 초면 끝난다.
- slop.sh 가 0 이 안 되면 2번 고치고 멈추고 질문한다. 끝없이 고치지 않는다.

규칙 늘리기: AI 코드에서 싫은 패턴을 볼 때마다 slop.sh 에 1개 추가.

## PLAN 13. merge 사고 방지

### 무슨 일

오래 떨어진 브랜치를 AI 에게 "머지해" 통째로 맡김. AI 는 양쪽 의도를 모르고, 그럴듯한 새 코드를 지어내서 "합침". 검사할 방법이 없어서 그대로 들어감.

### 규칙 (safe-merge skill)

1. 시작 전 백업: `git branch backup/<나>-$(date +%m%d%H%M)`
2. 충돌 파일 목록: `git diff --name-only --diff-filter=U`
3. 파일 1개씩 푼다. 통째 금지.
4. 양쪽 의도를 본다: `git log --oneline HEAD..MERGE_HEAD -- <파일>`, `git log --oneline MERGE_HEAD..HEAD -- <파일>`
5. 결과의 모든 줄은 양쪽 중 한쪽에 있던 줄. 새 코드가 꼭 필요하면 멈추고 질문.
6. lock 파일(package-lock.json 등)은 AI 금지. 오프라인이라 다시 만들 수 없음.

### merge-check.sh (테스트함)

머지 commit 의 combined diff 에서 `++` 로 시작하는 줄 = 두 부모 모두에 없던 줄. 스크래치 repo 에서 확인: 지어낸 줄 1개 넣은 머지 → 그 줄 출력 + exit 1, 양쪽 줄만 쓴 머지 → exit 0.

```sh
#!/usr/bin/env sh
# 사용: sh scripts/merge-check.sh  (머지 commit 직후, push 전)
cd "$(git rev-parse --show-toplevel)" || exit 2
BAD=$(git show --cc HEAD | grep '^++[^+]')
MARK=$(git grep -nE '^(<<<<<<<|>>>>>>>)( |$)' HEAD -- . ':!scripts/merge-check.sh')
[ -z "$BAD$MARK" ] && { echo "merge-check OK"; exit 0; }
[ -n "$BAD" ] && { echo "양쪽에 없던 줄:"; echo "$BAD"; }
[ -n "$MARK" ] && { echo "충돌 마커:"; echo "$MARK"; }
exit 1
```

권장 git 설정 (1회): `git config --global merge.conflictstyle zdiff3` (충돌에 원래 코드도 보임, git 2.35 이상), `git config --global rerere.enabled true` (푼 충돌 기억).

## PLAN 14. 설계 잠금 + demo 모드

### 무슨 일

- Object 에 input 1개 넣는 일. AI 가 테스트를 너무 많이 요구.
- 사람: "일단 넣고 보여주자. 오늘 시연."
- AI: 설계 버림. JSON 컬럼 1개에 전부 넣음. 정리가 더 오래 걸림.

### 왜

1. **"빨리" 의 범위가 없었다.** 무엇을 풀고(테스트) 무엇을 지키는지(설계) 안 적혀 있었다.
2. **설계가 파일에 없었다.** 대화 안에만 있으면 압박 한 마디에 사라진다.
3. **기계 검사가 없었다.** md 규칙은 AI 가 무시할 수 있다. 명령은 무시 못 한다.
4. **테스트 양 기준이 없었다.** 그래서 처음에 테스트가 과했고, 피곤해서 "다 빼" 가 나왔다.

### 1. 설계 파일 (코드 전에)

```
Object type: <이름>
property: 이름:타입 (한 줄씩)
입력 → property 매핑: 입력칸 → property
하지 말 것: JSON/문자열 한 칸에 몰아넣기
```

일감 파일의 "배경" 에 이 경로를 적는다. 다음 세션에서 AI 가 읽는다.

### 2. demo 모드

AGENTS.md 1줄. `demo` = 테스트를 확인 1개로 줄임 (넣고 → 읽어서 → 값이 보임). 설계는 그대로. 사람은 "일단 넣고 보자" 대신 `demo` 라고 친다. 평소 테스트 = 정상 1, 실패 1, 경계 1. 더 하려면 질문.

### 3. 멈추고 질문

AGENTS.md 1줄. 아래면 코드 전에 멈추고 질문 (선택지 abc + 추천):

- Object type, property, 컬럼, 매핑 변경
- 여러 값을 JSON/문자열 한 칸에 넣기
- 내 지시가 설계와 부딪힘 (설계가 지시보다 우선)
- 같은 에러 2번

### 4. design-check.sh

commit 안 한 변경(또는 기준 이후)의 추가된 줄에서 `JSON.stringify json.dumps to_json JSON.parse json.loads` 를 찾는다. 있으면 경로:줄 출력, exit 1. 스크래치 git repo 에서 확인: 깨끗 → 0, `json.dumps` 1줄 추가 → 1, commit 후 `HEAD~1` 기준 → 1.

```sh
#!/usr/bin/env sh
# 사용: sh scripts/design-check.sh [기준]  (기본 HEAD = commit 안 한 변경)
cd "$(git rev-parse --show-toplevel)" || exit 2
BASE=${1:-HEAD}
OUT=$(git diff -U0 "$BASE" -- . ':!docs' ':!.harness' ':!scripts/design-check.sh' \
  | grep -E '^\+\+\+ |^\+' \
  | awk '/^\+\+\+ /{f=substr($2,3);next} /JSON\.stringify|json\.dumps|to_json|JSON\.parse|json\.loads/{print f": "$0}')
[ -z "$OUT" ] && { echo "design-check OK"; exit 0; }
echo "$OUT"; echo "설계 확인 필요: JSON 몰아넣기?"; exit 1
```

한계: 새 파일(untracked)은 `git diff` 에 안 나온다 (`git add -N` 필요). 정당한 JSON 사용도 걸린다 (사람이 보고 OK). property 이름이 설계와 맞는지는 검사 안 함.

## PLAN 15. 모름 먼저

### 무슨 일

Foundry 문서는 개념만 많고 "이렇게 하면 이렇게 된다" 가 적다. AI 는 빈 곳이 많은 설계로 테스트 코드를 짜고, 돌려보며 설계를 고친다 (PoC 식). 그래서 오래 걸린다.

### 왜 오래 걸리나

1. **모르는 것이 안 보인다.** 설계 안에 숨어 있다가 구현 중에 하나씩 터진다.
2. **확인 순서가 비싸다.** 사람에게 묻거나 확인된 사실을 보는 것이 코드 실행보다 싸다.
3. **확인한 사실이 사라진다.** 다음 세션이 또 테스트한다.
4. **테스트 1개 = 모름 1개.** 여러 개를 한 번에 확인하지 않는다.

### 규칙

0. **거르기.** 모름마다 "틀리면 설계 바뀜?" 아니오 = 확인 안 함. 설계 파일 `## 가정` 에 1줄 + 코드에 `ASSUMPTION:` 주석. 그곳은 함수 1개 뒤에 숨김.
1. "예" 인 것만 설계 파일 `## 모름` 에 1줄씩. 예: "Action 으로 만든 Object 가 바로 검색되나?"
2. 모름마다 싼 순서로: (a) `.memory/facts/foundry.md`, MCP cache, MCP 문서 찾기 (b) 사람에게 한 번에 질문, abc + 추천 (c) 그래도 모르면 probe 1개: `.work/<나>/probe/` 에 20줄 이하, 남은 모름을 한 번에 확인. probe 실행 3번 넘으면 멈추고 보고.
3. 결과는 `foundry.md` 에 1줄: `날짜 | 사실 | 확인 명령`.
4. 모름 0개 = 설계 확정. 그 다음 구현. 가정이 틀리면 그 함수만 고침, 전체 재설계 금지.
5. 구현 중 새 모름 → 멈추고 처음(0번)부터. 설계를 몰래 바꾸지 않는다.
6. probe 코드는 구현에 복사 금지.

효과는 추정이다: 테스트 횟수가 "모름 개수만큼" 에서 "설계를 바꾸는 모름에 대해 probe 1~2번" 으로 준다. 실제 사용으로 확인 필요.

## 다른 설계안과 비교한 결과

같은 문제를 다른 방식으로 푼 안과 비교했다. 그쪽에서 가져온 것:

| 가져온 것 | 왜 |
|---|---|
| 설계 바뀜? 필터 | 설계를 안 바꾸는 모름은 테스트 안 함. 가정 + `ASSUMPTION:` 주석. 테스트가 가장 많이 준다. |
| 평소 테스트 양 | 정상1 실패1 경계1. demo 만 있으면 평소에 또 과잉. |
| 지시 vs 설계 | 부딪히면 설계 우선, 질문. |
| 2번 실패, probe 3번 | 같은 에러 2번, probe 실행 3번 넘으면 멈춤. (처음엔 30분. AI 는 시간 재기가 약해서 횟수로 바꿈) |
| `## 가정` 칸 | 가정이 코드 주석만이 아니라 설계 파일에도 남는다. |

이쪽을 유지한 것:

- 규칙은 PLAN 1줄 + AGENTS.md. 긴 템플릿은 손으로 매 세션 치기 어렵다.
- 사람에게 먼저 묻기.
- probe 1개로 여러 모름을 한 번에.
- design-check.sh 기계 검사.

## 칠 것

PLAN.md 끝에 추가 (한 번):

```
12 slop: skill lean-code(모르면 질문, 요청한 줄만, 새 파일/추상화 금지, 표준 library 우선, 시작 전 확인 명령 1개 정함, 새 테스트 파일 금지). skill verify-done(완료 전 그 확인 명령 1개만 다시 실행, 결과 붙임, "될 거/아마" 금지, 테스트 추가 금지. 테스트 양은 14 를 따름). slop.sh 는 테스트 아님(검색만). 0 안 되면 2번 고치고 멈추고 질문. scripts/slop.sh: which 로 있는 linter 쓰고(설치 금지) 없으면 rg 로 console.log, 주석 코드, TODO, any, 빈 catch → 경로:줄, exit 1. AGENTS.md 에 1줄: 코드 고칠 땐 lean-code, 끝나면 slop.sh 0 될 때까지, 그 다음 verify-done.
확인: console.log 1줄 넣고 sh scripts/slop.sh; echo $? → 1. 지우면 0.

13 merge: skill safe-merge(백업 브랜치, 충돌 파일 1개씩, 양쪽 git log 의도 확인, 결과 줄은 양쪽에 있던 줄만, 새 코드 필요하면 멈추고 질문, lock 파일 금지). scripts/merge-check.sh: 머지 commit 에서 git show --cc HEAD | grep '^++[^+]' 0줄 + 충돌 마커 0개 아니면 exit 1. AGENTS.md 1줄: 충돌은 safe-merge 로만.
확인: 일부러 충돌 만들고 지어낸 줄 1개 넣은 머지 → merge-check.sh 가 그 줄 출력, exit 1.

14 설계잠금: 기능마다 코드 전에 docs/design/<기능>.md (Object type, property 이름:타입, 입력→property). AGENTS.md 3줄: 1 demo = 테스트만 확인 1개(넣고 읽어서 값 보임), 설계 그대로. 평소 테스트 = 정상1 실패1 경계1, 더는 질문. 2 type, property, 매핑 변경이나 JSON/문자열 한 칸 몰아넣기, 내 지시가 설계와 부딪힘, 같은 에러 2번 = 멈추고 질문(abc+추천). 설계가 지시보다 우선. 3 끝나면 scripts/design-check.sh 0 될 때까지. design-check.sh: git diff -U0 ${1:-HEAD} 추가 줄에서 JSON.stringify json.dumps to_json JSON.parse json.loads 찾으면 경로:줄, exit 1. docs .harness 제외.
확인: json.dumps 1줄 넣고 sh scripts/design-check.sh; echo $? → 1. 지우면 0.

15 모름 먼저: docs/design/<기능>.md 에 "## 가정" 칸과 "## 모름" 칸. 코드 전에 모르는 Foundry 동작마다 "틀리면 설계 바뀜?" 아니오 = 확인 안 함, ## 가정 1줄 + 코드에 ASSUMPTION: 주석, 그곳은 함수 1개 뒤에 숨김. 예 = ## 모름 1줄. 모름마다: 1 .memory/facts/foundry.md, MCP cache, MCP 문서 먼저 찾음 2 없으면 나에게 한 번에 질문(abc+추천) 3 그래도 모르면 probe: .work/<나>/probe/ 에 파일 1개 20줄 이하, 모름 여러 개를 한 번에, probe 실행 3번 넘으면 멈춤 4 결과는 foundry.md 에 1줄(날짜, 사실, 확인 명령). 모름 0 개 = 설계 확정 → 구현. 가정이 틀리면 그 함수만 고침. 구현 중 새 모름 → 멈추고 처음부터. probe 코드는 구현에 복사 금지.
확인: 가짜 기능에 모름 3개(1개는 설계 안 바뀜) → 1개는 ASSUMPTION, 나머지는 먼저 찾고 질문, probe 는 1개만.
```

그 다음:

```
PLAN 12 해
PLAN 13 해
PLAN 14 해
PLAN 15 해
```

지금 하던 기능:

```
docs/design/<기능>.md 에 가정 목록과 모름 목록만 써. 각 모름에 "틀리면 설계 바뀜?" 적어. 코드 금지. 다 쓰면 나에게 한 번에 질문.
```

급할 때:

```
demo
```

전제: 이 PLAN 은 기존 하네스 0~11 단계 위에 얹는다 (`.memory/facts`, MCP cache, AGENTS.md 60줄 이하 규칙). 12, 13 이 없어도 14, 15 는 동작한다. 12 는 테스트 양을 14 에서 가져오므로 12 를 넣을 땐 14 도 넣는다.
