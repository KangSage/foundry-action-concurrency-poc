# source-revision 구현 명세

> 설계: [source-revision.md](source-revision.md). 앞 단계: [ingest-filter.md](ingest-filter.md) (끝난 상태 전제).
> **내부 AI에게:** [AGENTS.md](../../AGENTS.md) 규칙대로. 맨 아래 "채울 것" 표 먼저. 채운 값은 이 repo에 커밋하지 않는다.

## 만들 것 (원천 1개 기준)

| dataset | 만드는 transform | 쓰기 |
|---|---|---|
| `revision/{{원천코드}}_REVISION` | `compute_revision` | incremental APPEND |
| `revision/{{원천코드}}_RECEIPT` | `compute_revision` (같은 transform, 출력 2개) | incremental APPEND |
| `revision/{{원천코드}}_HEAD` | `compute_head` | SNAPSHOT |

코드: [examples/source-revision/](../../examples/source-revision/)

| 파일 | 내용 |
|---|---|
| `revision_logic.py` | 순수 로직 (Spark DataFrame만). 설정 상수 4개가 빈칸 |
| `revision_transforms.py` | Foundry transform 2개 (`compute_revision`, `compute_head`) |
| `test_revision.py` | 합성 데이터 6회 실행 시나리오 테스트 |
| `conftest.py` | **로컬 전용.** Foundry 레포에는 넣지 않음 (`spark_session` fixture가 이미 있음) |

## 순서

1. `revision_logic.py`의 설정 4개 채움: `SRC_SYSTEM`, `KEY`, `COMPARE_COLS`, `KEEP_COLS`.
2. 두 파일을 transforms 레포에 넣음. `revision_transforms.py`의 import 경로·`ROOT`·`CODE` 채움.
3. `test_revision.py`를 레포 테스트 폴더에 넣고 테스트 실행 → 통과 확인. 테스트는 합성 컬럼(`k`, `a`, `b`)이라 그대로 둠.
4. **브랜치에서** 빌드: `compute_revision` → `compute_head`. ([Branch settings](https://www.palantir.com/docs/foundry/code-repositories/branch-settings))
5. 브랜치에서 확인 (아래 "완료 기준").
6. main 병합 → main에서 첫 빌드 → 스케줄 설정.

## 동작 요약

- 입력: 내부 마스터 (ingest-filter ②) + 복사본 (ingest-filter ①, 삭제 판정용 키만) + 이전 REVISION.
- 첫 빌드: 이전 REVISION 없음 → 모든 행 `src_rev_no = 0`, INSERT.
- 이후: 키별 최신 리비전과 `row_hash` 비교 → 바뀐 행만 APPEND.
- `row_hash` = `COMPARE_COLS` 값을 문자열로 바꾸고 앞뒤 공백 제거, null은 고정 기호 → sha256. 그래서 `"x "`와 `"x"`는 같고, null과 `""`는 다름.
- 사라진 행: 복사본에 키가 있으면 OUT_OF_SCOPE, 없으면 DELETE. 값은 마지막 값 유지.
- 사라졌던 행이 다시 오면 REINSERT.
- RECEIPT: 실행 1회 = 1행. 변경 없어도 1행 남음 (건수 0).

## 스케줄

- `compute_revision`: 내부 마스터 갱신 시 트리거.
- `compute_head`: REVISION 갱신 시 트리거.
- ([Schedules](https://www.palantir.com/docs/foundry/data-integration/schedules))

## 이력 보호 (중요)

- `require_incremental=True`: 증분 실행이 안 되면 **실패**시킴. 실패가 낫다. 비증분으로 돌면 출력이 교체되어 이력이 사라짐.
- `semantic_version`은 **올리지 않는다.** 올리면 비증분 + 교체 모드. ([Create a historical dataset](https://www.palantir.com/docs/foundry/transforms-python/create-historical-dataset))
- `COMPARE_COLS` 순서·목록을 바꾸면 모든 행 해시가 바뀌어 전체가 새 리비전이 됨. 바꿀 때는 사용자에게 먼저 물음.
- REVISION을 손으로 고치거나 지우지 않는다. HEAD는 언제든 다시 만들 수 있음.

## 확인 필요 (브랜치에서 처음 빌드할 때 볼 것)

- `require_incremental=True`일 때 **첫 빌드**가 통과하는지. 실패하면 첫 빌드만 이 옵션을 빼고 돌리고, 다음 빌드부터 다시 켬.
- incremental transform 1개가 출력 2개(REVISION·RECEIPT)를 같이 쓰는 것. 안 되면 RECEIPT를 별도 transform으로 나눔 (REVISION의 `receipt_id`별 집계).
- `revision.dataframe("previous", schema=...)` 스키마가 실제 출력과 같아야 함. 다르면 빌드 실패 → `revision_schema()`를 출력 컬럼 순서와 맞춤.

## 완료 기준

- [ ] 테스트 통과.
- [ ] 첫 빌드: REVISION 행 수 = 내부 마스터 행 수. 전부 `src_rev_no = 0`, INSERT.
- [ ] 같은 입력으로 다시 빌드: REVISION 행 수 그대로. RECEIPT 1행 추가 (건수 전부 0).
- [ ] HEAD 행 수 = REVISION의 고유 키 수.
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
| `KEEP_COLS` | REVISION에 보관할 컬럼 (`COMPARE_COLS` 포함) | 내부 마스터 스키마 | "어느 컬럼을 보관하나? 전부?" |
| `ROOT` | 우리 Foundry Project 경로 | ingest-filter와 같음 | - |
| `CODE` | dataset 이름 앞부분 | ingest-filter와 같음 | - |
| import 경로 | `revision_logic` 위치 | transforms 레포 구조 | - |
