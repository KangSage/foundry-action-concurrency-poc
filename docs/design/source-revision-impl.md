# source-revision 구현 명세

> 설계: [source-revision.md](source-revision.md). 앞 단계: [ingest-filter.md](ingest-filter.md) (끝난 상태 전제).
> **내부 AI에게:** [AGENTS.md](../../AGENTS.md) 규칙대로. 맨 아래 "채울 것" 표 먼저. 코드는 이 명세대로 직접 작성한다. 채운 값은 이 repo에 커밋하지 않는다.

## 만들 것 (원천 1개 기준)

| transform | 입력 | 출력 | 쓰기 |
|---|---|---|---|
| `compute_revision` | 내부 마스터 (ingest-filter ②), 복사본 (ingest-filter ①), 이전 REVISION | `revision/{{원천코드}}_REVISION`, `revision/{{원천코드}}_RECEIPT` | incremental, 둘 다 APPEND |
| `compute_head` | REVISION | `revision/{{원천코드}}_HEAD` | SNAPSHOT |

`compute_revision` 설정:
- 내부 마스터 · 복사본은 snapshot input (매번 전체를 읽음).
- 이전 REVISION은 출력의 `previous`로 읽음. 스키마를 직접 지정해야 함 (아래 REVISION 컬럼 순서). ([Create a historical dataset](https://www.palantir.com/docs/foundry/transforms-python/create-historical-dataset))
- `require_incremental` 켬. `semantic_version`은 처음 값에서 바꾸지 않음 (아래 "이력 보호").

## 설정값 4개

| 이름 | 뜻 |
|---|---|
| `SRC_SYSTEM` | 원천 코드 (문자열 상수) |
| `KEY` | 원천 업무 키 컬럼 1개 |
| `COMPARE_COLS` | 바뀌면 새 리비전이 되는 컬럼 목록. **순서 고정** |
| `KEEP_COLS` | REVISION에 보관할 컬럼 목록. `KEY`와 `COMPARE_COLS` 포함 |

## REVISION 컬럼 (이 순서)

| # | 컬럼 | 타입 | 값 |
|---|---|---|---|
| 1 | `src_system` | string | `SRC_SYSTEM` |
| 2 | `KEY` 컬럼 | 마스터와 같음 | 키 |
| 3 | `src_rev_no` | int | 아래 판정표 |
| 4 | `change_type` | string | 아래 판정표 |
| 5 | `row_hash` | string | 아래 해시 규칙 |
| 6 | `receipt_id` | string | 이번 실행의 RECEIPT id |
| 7 | `captured_at` | timestamp | 이번 실행 시각 (UTC) |
| 8~ | `KEEP_COLS` (키 제외) | 마스터와 같음 | 아래 판정표 |
| 끝 | `revision_pk` | string | `src_system` + `_` + 키 + `_` + `src_rev_no` |

## 해시 규칙 (`row_hash`)

1. `COMPARE_COLS`를 정해진 순서로 하나씩 처리.
2. 값을 문자열로 바꾸고 앞뒤 공백을 지움.
3. null이면 고정 기호 1개로 바꿈 (빈 문자열 `""`와 달라야 함).
4. 구분 문자 (데이터에 안 나오는 문자 1개)로 이어 붙임.
5. sha256 hex.

결과: `"x "`와 `"x"`는 같은 해시. null과 `""`는 다른 해시.

## 판정표 (키 1개 기준)

먼저 이전 REVISION에서 키별 **최신 행** (`src_rev_no`가 가장 큰 행)을 찾는다. "최신 = 사라짐"은 최신 행의 `change_type`이 DELETE 또는 OUT_OF_SCOPE라는 뜻.

| 마스터에 키 | 최신 행 | 조건 | 새 행 `change_type` | 새 `src_rev_no` | 업무 컬럼 값 |
|---|---|---|---|---|---|
| 있음 | 없음 | - | INSERT | 0 | 마스터 값 |
| 있음 | 있음 | 최신 = 사라짐 | REINSERT | 최신 + 1 | 마스터 값 |
| 있음 | 있음 | 해시 다름 | UPDATE | 최신 + 1 | 마스터 값 |
| 있음 | 있음 | 해시 같음 | (새 행 없음) | - | - |
| 없음 | 있음 | 최신 = 사라짐 | (새 행 없음) | - | - |
| 없음 | 있음 | 복사본에 키 있음 | OUT_OF_SCOPE | 최신 + 1 | 최신 행 값 그대로 |
| 없음 | 있음 | 복사본에도 키 없음 | DELETE | 최신 + 1 | 최신 행 값 그대로 |

새 행만 REVISION에 추가한다. 기존 행은 절대 바꾸지 않는다.

## RECEIPT (실행 1회 = 1행)

| 컬럼 | 값 |
|---|---|
| `receipt_id` | `SRC_SYSTEM` + `_` + 실행 시각 (`yyyyMMddTHHmmss`, UTC) |
| `src_system` | `SRC_SYSTEM` |
| `insert_count` · `update_count` · `delete_count` · `reinsert_count` · `out_of_scope_count` | 이번에 추가한 새 행 수 (없으면 0) |
| `received_at` | 실행 시각 |
| `mirror_row_count` | 복사본 행 수 |
| `master_row_count` | 내부 마스터 행 수 |

변경이 없어도 1행 남긴다.

## HEAD

- REVISION에서 (`src_system`, 키)별 `src_rev_no`가 가장 큰 행 1개.
- 컬럼 = REVISION 컬럼 + `head_pk` (`src_system` + `_` + 키).
- 매번 전체 다시 계산.

## 테스트 시나리오 (합성 데이터)

키 `k`, 비교 컬럼 `a`, `b`, 원천 코드 `SYN`. 같은 출력을 이어서 6번 실행한다. 표의 "새 행"은 그 실행에서 REVISION에 추가되는 행 (`k`, `src_rev_no`, `change_type`, `a`).

| 회차 | 마스터 (`k`, `a`, `b`) | 복사본 키 | 새 행 |
|---|---|---|---|
| 1 | (1, x, p), (2, y, q) | 1, 2, 3 | (1, 0, INSERT, x), (2, 0, INSERT, y) |
| 2 | (1, `"x "`, p), (2, y, q) | 1, 2, 3 | 없음 (공백만 다름). RECEIPT 건수 모두 0 |
| 3 | (1, x2, p), (3, z, null) | 1, 2, 3 | (1, 1, UPDATE, x2), (2, 1, OUT_OF_SCOPE, y), (3, 0, INSERT, z) |
| 4 | (1, x2, p), (2, y, q) | 1, 2 | (2, 2, REINSERT, y), (3, 1, DELETE, z). RECEIPT: reinsert 1, delete 1, 복사본 2, 마스터 2 |
| 5 | (1, x2, p), (2, y, q) | 1, 2 | 없음 (3은 이미 DELETE) |
| 6 | (1, x2, p), (2, y, `""`) | 1, 2 | (2, 3, UPDATE, y) (`q` → `""`) |

6회 뒤 확인:
- HEAD = (1, 1, UPDATE), (2, 3, UPDATE), (3, 1, DELETE).
- REVISION 8행. `revision_pk` 중복 0. `SYN_2_3` 있음.
- 매 회차 새 행의 컬럼 이름·순서 = REVISION 스키마.

권장: 판정 로직을 Foundry API와 분리한 순수 함수로 만들고, 이 표를 단위 테스트로 옮긴다. 로직을 일부러 틀리게 바꾸면 테스트가 실패하는지도 한 번 본다.

## 순서

1. "채울 것" 표 채움 → 사용자 확인.
2. 판정 로직 + 위 테스트 작성 → 테스트 통과.
3. **브랜치에서** 빌드: `compute_revision` → `compute_head`. ([Branch settings](https://www.palantir.com/docs/foundry/code-repositories/branch-settings))
4. 브랜치에서 "완료 기준" 확인.
5. main 병합 → main 첫 빌드 → 스케줄.

## 스케줄

- `compute_revision`: 내부 마스터 갱신 시 트리거.
- `compute_head`: REVISION 갱신 시 트리거.
- ([Schedules](https://www.palantir.com/docs/foundry/data-integration/schedules))

## 이력 보호 (중요)

- `require_incremental` 켬: 증분 실행이 안 되면 **실패**. 비증분으로 돌면 출력이 교체되어 이력이 사라짐.
- `semantic_version` 올리지 않음. 올리면 비증분 + 교체. ([Create a historical dataset](https://www.palantir.com/docs/foundry/transforms-python/create-historical-dataset))
- `COMPARE_COLS` 순서·목록을 바꾸면 모든 행이 새 리비전. 바꾸기 전에 사용자에게 물음.
- REVISION을 손으로 고치거나 지우지 않음. HEAD는 언제든 다시 만들 수 있음.

## 확인 필요 (브랜치 첫 빌드 때)

- `require_incremental`을 켠 상태로 **첫 빌드**가 통과하는지. 실패하면 첫 빌드만 끄고, 다음부터 켬.
- incremental transform 1개가 출력 2개(REVISION · RECEIPT)를 같이 쓰는 것. 안 되면 RECEIPT를 별도 transform으로 (REVISION의 `receipt_id`별 집계).
- `previous` 스키마가 실제 출력과 다르면 빌드 실패 → 컬럼 순서를 위 표와 맞춤.

## 완료 기준

- [ ] 테스트 시나리오 통과.
- [ ] 첫 빌드: REVISION 행 수 = 내부 마스터 행 수. 전부 `src_rev_no = 0`, INSERT.
- [ ] 같은 입력으로 다시 빌드: REVISION 행 수 그대로. RECEIPT 1행 추가 (건수 모두 0).
- [ ] HEAD 행 수 = REVISION 고유 키 수.
- [ ] `revision_pk`, `head_pk` 중복 0.
- [ ] 우리 Foundry Project 권한: 관리자 외 사용자가 dataset을 못 봄 (퀵서치 포함).

## 다음 단계 (이번 범위 밖)

- REVISION · HEAD로 Object Type (PK = `revision_pk`, `head_pk`). 권한 속성은 edit-only (Action으로만).
- 내부 엔티티에 `pinned_src_rev_no` 속성 + "리비전 올리기" Action (담당자만).
- 화면 "새 리비전 있음" = HEAD `src_rev_no` > `pinned_src_rev_no`.

## 채울 것 (내부 AI)

| 빈칸 | 뜻 | 어디서 확인 | 모르면 사용자에게 |
|---|---|---|---|
| `SRC_SYSTEM` | 원천 코드 | ingest-filter의 `{{원천코드}}` | "원천 코드는?" |
| `KEY` | 원천 업무 키 컬럼 | 내부 마스터 스키마 | "행을 구분하는 키 컬럼은?" |
| `COMPARE_COLS` | 바뀌면 리비전이 되는 컬럼 | 내부 마스터 스키마 | "어느 컬럼이 바뀌면 새 리비전인가?" |
| `KEEP_COLS` | 보관할 컬럼 | 내부 마스터 스키마 | "어느 컬럼을 보관하나? 전부?" |
| `{{원천코드}}` · 경로 | dataset 위치 | ingest-filter와 같음 | - |
