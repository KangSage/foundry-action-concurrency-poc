# multi-source: 모든 외부 데이터에 같은 틀 적용

> 앞 문서: [ingest-filter.md](ingest-filter.md) · [source-revision.md](source-revision.md) · [source-revision-impl.md](source-revision-impl.md)
> **내부 AI에게:** [AGENTS.md](../../AGENTS.md) 규칙대로. 먼저 [prompts/source-inventory.md](../../prompts/source-inventory.md)로 원천 점검표를 만든다. 코드는 이 명세대로 직접 작성한다.

## 결론

- 외부 데이터는 원천마다 **같은 세트**를 만든다: 복사본 → 마스터 → REVISION · HEAD · RECEIPT.
- 로직은 하나. 원천마다 다른 것은 **설정 1행**뿐.
- 설정 목록 1개에서 원천별 transform을 찍어 낸다 (generated transform). 원천 추가 = 설정 1행 추가.
- 업무 키가 있는 원천 = **ROW 모드** (행별 리비전, source-revision-impl 그대로).
- 업무 키가 없는 원천 = **WHOLE 모드** (동기화 결과 통째로 1리비전, 아래).

## 설정 목록 (원천 1개 = 1행)

| 항목 | 뜻 | ROW | WHOLE |
|---|---|---|---|
| `SRC_SYSTEM` | 원천 코드. 원천마다 다름 | 필수 | 필수 |
| `SOURCE_PATH` | 원천 dataset 경로 | 필수 | 필수 |
| `MODE` | `ROW` 또는 `WHOLE` | 필수 | 필수 |
| `FILTER` | 마스터 필터 조건 (없으면 전체) | 선택 | 선택 |
| `KEEP_COLS` | 보관 컬럼 | 필수 | 필수 |
| `KEY` | 업무 키 컬럼. 여러 컬럼 묶음도 가능 | 필수 | 없음 |
| `COMPARE_COLS` | 변경 감지 컬럼 (순서 고정) | 필수 | 필수 (행 해시용) |
| `SCHEDULE` | 복사 주기 | 필수 | 필수 |

- 설정 목록은 사내 레포에만 둔다 (경로·컬럼명이 업무 정보).
- 복합 키: 키 컬럼 값을 정해진 순서로 구분 문자와 이어 붙인 문자열 1개를 키로 쓴다. 판정표는 같다.

## 이름 규칙 (원천별)

| dataset | 이름 |
|---|---|
| 복사본 | `raw/<SRC_SYSTEM>_mirror` |
| 마스터 | `master/<SRC_SYSTEM>_master` |
| REVISION · RECEIPT · HEAD | `revision/<SRC_SYSTEM>_REVISION`, `_RECEIPT`, `_HEAD` |
| 모아 보기 (선택) | `revision/RECEIPT_ALL` = 모든 원천 RECEIPT union (SNAPSHOT) |

dataset 1개는 transform 1개만 쓸 수 있으므로 원천별로 분리한다.

## ROW 모드

[source-revision-impl.md](source-revision-impl.md) 그대로. `SRC_SYSTEM`, `KEY`, `COMPARE_COLS`, `KEEP_COLS`를 설정 행에서 읽는다.

### 키 검증 (추천안, 사용자 확정 전)

| 경우 | 처리 |
|---|---|
| 키 null 또는 빈 값 | 빌드 실패. 메시지에 건수 |
| 마스터 안에 같은 키 2행 이상 | 빌드 실패. 메시지에 건수 |
| 키 값이 바뀜 | 감지 불가. 옛 키 DELETE + 새 키 INSERT로 남음 → 원천 쪽과 "키 불변" 합의 |

실패가 낫다: 잘못 쌓인 리비전은 지울 수 없다. 단점: 원천 1행 문제로 그 원천 갱신 전체가 멈춘다.

## WHOLE 모드 (키 없는 원천)

동기화 결과가 이전과 다르면 **마스터 전체를 새 리비전으로** 쌓는다.

| 항목 | 규칙 |
|---|---|
| 행 해시 | `COMPARE_COLS`로 행마다 해시 (source-revision-impl 해시 규칙) |
| 스냅샷 해시 | 행 해시를 정렬해 이어 붙인 뒤 sha256. 행 순서와 무관 |
| 판정 | 스냅샷 해시가 최신 리비전과 같으면 새 행 없음. 다르면 마스터 전 행을 새 `src_rev_no`로 APPEND |
| `src_rev_no` | 원천 전체 기준 0부터 +1 (키별 아님) |
| `change_type` | 첫 리비전 `INSERT`, 이후 `SNAPSHOT` |
| 행 PK | `SRC_SYSTEM` + `_` + `src_rev_no` + `_` + 행 순번 (같은 리비전 안 행 해시 정렬 순서, 0부터) |
| HEAD | 최신 `src_rev_no`의 행 전부 |
| RECEIPT | ROW와 같음. 건수 칸 대신 `changed` (true/false), `row_count` |
| 내부 고정 참조 | `(SRC_SYSTEM, pinned_src_rev_no)` |
| "새 리비전 있음" | HEAD의 `src_rev_no` > `pinned_src_rev_no` |

비용: 바뀔 때마다 전체를 복사한다. 변경이 드문 원천에만 맞다. 자주 바뀌고 크면 키를 만들 방법을 먼저 찾는다 (사용자에게 질문).

### WHOLE 테스트 시나리오 (합성)

| 회차 | 마스터 (`a`, `b`) | 새 행 |
|---|---|---|
| 1 | (x, p), (y, q) | rev 0, INSERT 2행 |
| 2 | (y, q), (x, p) | 없음 (순서만 다름) |
| 3 | (x, p), (y, q2) | rev 1, SNAPSHOT 2행 |
| 4 | (x, p), (y, q2), (z, r) | rev 2, SNAPSHOT 3행 |
| 5 | 4회차와 같음 | 없음 |

5회 뒤: HEAD = rev 2의 3행. RECEIPT 5행 (`changed` = T, F, T, T, F).

## 순서

1. [prompts/source-inventory.md](../../prompts/source-inventory.md)로 원천 점검표 작성 → 사용자 확인 (원천별 MODE 확정).
2. 설정 목록 작성 (사내 레포).
3. 이미 만든 원천 1개 (ingest-filter · source-revision 구현분)를 설정 목록 방식으로 옮김. **출력 dataset 경로는 그대로** 둔다 (이력 유지).
4. ROW 원천 추가 → 브랜치 빌드 → 완료 기준 (source-revision-impl).
5. WHOLE 원천이 있으면 WHOLE 로직 + 위 테스트 → 브랜치 빌드.

## 확인 필요

- generated transform (반복문으로 transform 여러 개 만들기)을 회사 Foundry 버전의 Python transforms에서 쓸 수 있는지, 설정 파일을 레포에서 읽는 방법.
- 기존 원천 1개를 옮길 때 transform 이름·경로가 바뀌어도 출력 dataset의 이력이 유지되는지. 안 되면 옮기지 말고 그대로 둔다.

## 채울 것 (내부 AI)

| 빈칸 | 어디서 확인 | 모르면 사용자에게 |
|---|---|---|
| 원천 목록 · 모드 | 원천 점검표 | "이 원천들 맞나? 각각 ROW/WHOLE 맞나?" |
| 원천별 `SRC_SYSTEM` | - | "원천별 코드는?" |
| 원천별 `KEY` | 점검표 키 후보 | "이 원천 키는 이 컬럼(묶음) 맞나?" |
| 원천별 `COMPARE_COLS` · `KEEP_COLS` | 점검표 + 스키마 | "바뀌면 리비전이 되는 컬럼은? 기술 컬럼 빼는 것 맞나?" |
| 키 검증 실패 처리 | 위 추천안 | "키 null·중복이면 빌드 실패로 할까?" |
