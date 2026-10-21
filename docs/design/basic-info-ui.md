# U1 기본 정보 화면 ↔ Ontology 연동 (공개용)

> 이 문서는 퍼블릭 repo로 공유된다. 업무 내용은 `{{빈칸}}`으로 둔다.
> **내부 AI에게:** 맨 아래 "채울 것" 표를 먼저 채운다. 모르면 사용자에게 표의 질문을 그대로 묻는다. 채운 값은 퍼블릭 repo에 다시 올리지 않는다.
> 선행 문서: [source-revision.md](source-revision.md) (D7).
> 상태: 초안 (2026-10-21). 범위 = "원천 값 조회 + 내부 값 편집 + 리비전 올리기" (사용자 결정, 10-21).

## 결론

- 화면 1개 = `{{내부 엔티티}}` 객체 1개의 기본 정보.
- 위쪽 = 원천 값. **고정 리비전**(`pinned_src_rev_no`)의 REVISION 객체에서 읽는다. 조회만.
- 아래쪽 = 내부 값. Action으로만 편집.
- 원천이 바뀌면 배지만 보여 준다 ("새 리비전 있음", "원천에서 삭제됨", "범위 밖").
- 리비전 올리기 = 별도 Action. 차이 표를 보여 주고, 사유를 받고, 이력을 남긴다.
- 원천 값은 앱에서 절대 편집하지 않는다 (D4, D7). 편집하면 이후 데이터셋 값이 영원히 가려진다. ([How user edits are applied](https://www.palantir.com/docs/foundry/object-edits/how-edits-applied/))

## 화면 영역

| 영역 | 내용 | 데이터 출처 | 편집 |
|---|---|---|---|
| A. 원천 정보 | `{{원천 표시 필드 목록}}` | REVISION 객체 (고정 rev) | 안 됨 |
| B. 리비전 배지 | "원천 v{pinned}" + 상태 배지 | 내부 객체 + HEAD 객체 | 안 됨 |
| C. 차이 보기 | 고정 rev vs 최신 rev 필드별 차이 | REVISION 2행 비교 | 안 됨 |
| D. 내부 정보 | `{{내부 편집 필드 목록}}` | 내부 객체 | Action ① |
| E. 리비전 올리기 버튼 | 최신 rev로 고정 변경 | Action ② | 권한자만 |
| F. 마지막 확인 시각 | 원천 마지막 수신 시각 | RECEIPT 최신 1행 | 안 됨 |

리비전 표시 형식: 원천 = `{{원천 리비전 표시 형식}}` (제안: "S0, S1…"). 내부 = `{{내부 리비전 표시 형식}}`. 두 번호를 섞지 않는다 (D7 격리 규칙).

## Object Type과 Link

| Object Type | PK | 역할 | 값 출처 |
|---|---|---|---|
| `원천리비전_REVISION_{{원천코드}}` | `src_system` + `_` + `biz_key` + `_` + `src_rev_no` | 모든 리비전. 고정 참조 대상 | transform (D7) |
| `원천리비전_HEAD_{{원천코드}}` | `src_system` + `_` + `biz_key` | 키별 최신 1행 | transform (D7) |
| `원천리비전_RECEIPT_{{원천코드}}` | `receipt_id` | 수신 기록 | transform (D7) |
| `{{내부 엔티티}}` | `{{내부 PK 규칙}}` | 화면의 주인 | Action |
| `{{내부 엔티티}}_PIN_HISTORY` | 생성 ID | 리비전 올리기 이력 | Action ② |

내부 엔티티에 새로 둘 속성 (모두 Action만 씀):

| 속성 | 뜻 |
|---|---|
| `src_system` | 원천 코드 |
| `biz_key` | 원천 키 |
| `pinned_src_rev_no` | 고정 리비전 번호 (0부터) |
| `pinned_rev_pk` | REVISION PK 문자열. Link 외래 키 (FK) |
| `head_pk` | HEAD PK 문자열. Link 외래 키 |
| `work_version` | 낙관적 잠금 (optimistic lock, 저장 충돌 감지 번호) |
| `pinned_by` / `pinned_at` | 마지막으로 고정을 바꾼 사람·시각 |

Link Type 2개 (내부 엔티티 → 원천, 다대일):

```mermaid
flowchart LR
  INT["{{내부 엔티티}}"] -->|"pinned_rev_pk → REVISION.PK"| REV["REVISION (고정 rev)"]
  INT -->|"head_pk → HEAD.PK"| HEAD["HEAD (최신)"]
  INT -->|"1:N"| PH["PIN_HISTORY"]
  HEAD -.->|"src_system"| RCP["RECEIPT 최신 1행"]
```

- PK가 여러 컬럼 조합이면 Link를 바로 못 건다. 그래서 PK 문자열을 내부 객체에 미리 만들어 둔다. ([Create an object type](https://www.palantir.com/docs/foundry/object-link-types/create-object-type/))
- `pinned_rev_pk`, `head_pk`는 문자열 조합이다. 규칙 기반 Action은 문자열 조합을 못 한다 → Function-backed Action으로 만든다 (PoC 관찰).
- 확인 필요: 회사 온톨로지(legacy 권한 모델)에서 edit-only 속성을 Link FK로 쓸 수 있는지.

## 화면 로드 순서 (OSDK)

| 순서 | 무엇 | OSDK 동작 | 실패 시 |
|---|---|---|---|
| 1 | 내부 객체 1개 | PK로 1건 조회 | 404 = "권한 없음 또는 없음" 한 문구 |
| 2 | 고정 REVISION | Link 따라가기 (고정 rev) | 없음 = "원천 리비전 없음" 오류 표시 |
| 3 | HEAD | Link 따라가기 (최신) | 없음 = 배지 숨김 |
| 4 | RECEIPT 최신 1행 | `src_system` 필터 + 시각 내림차순 1건 | 없음 = "확인 시각 없음" |
| 5 | 내 권한 | 앱 권한 판정 (D6 / KS 권한 패턴) | 편집 버튼 숨김 |

- 2~4는 1 다음에 병렬로 부른다.
- 차이 보기(C)는 버튼을 누를 때만 최신 REVISION 1건을 더 읽는다.
- 근거: [TypeScript OSDK](https://www.palantir.com/docs/foundry/ontology-sdk/typescript-osdk/)

## 배지 판정표

| HEAD.`src_rev_no` vs `pinned_src_rev_no` | HEAD.`change_type` | 배지 | 리비전 올리기 |
|---|---|---|---|
| 같음 | 아무거나 | 없음 ("최신") | 숨김 |
| 큼 | INSERT / UPDATE / REINSERT | "새 리비전 있음" | 가능 |
| 큼 | DELETE | "원천에서 삭제됨" | `{{삭제 시 처리}}` (기본: 막음) |
| 큼 | OUT_OF_SCOPE | "범위 밖" | `{{범위 밖 처리}}` (기본: 막음) |
| 작음 | - | "데이터 오류" | 숨김. 관리자 알림 |
| HEAD 없음 | - | "원천 없음" | 숨김 |

## 차이 보기 규칙

- 비교 필드 = D7 해시 비교 컬럼 목록과 **같은 설정**을 쓴다. 두 목록을 따로 두지 않는다.
- 필드별로 "이전 값 → 새 값"만 보여 준다. 같은 필드는 접는다.
- 값 정규화(공백, 숫자 형식, null)도 D7과 같은 규칙. 다르면 "차이 없음인데 배지 있음"이 생긴다.

## Action ① 내부 정보 편집

| 파라미터 | 형식 | 규칙 |
|---|---|---|
| 대상 객체 | 내부 엔티티 | 필수 |
| `{{내부 편집 필드}}` 각각 | `{{형식}}` | `{{검증 규칙}}` |
| `expected_work_version` | 정수 | 화면이 읽은 값 |

- Function-backed Action. `work_version`이 다르면 `UserFacingError`로 "다른 사람이 먼저 저장. 새로 불러온 뒤 다시". ([User-facing errors](https://www.palantir.com/docs/foundry/functions/user-facing-error/))
- 성공하면 `work_version + 1`.
- 원천 속성(`src_system`, `biz_key`, 고정 rev 관련)은 파라미터에 없다.
- 제출 조건: `{{편집 권한 그룹}}` 소속 + 행 권한. ([Submission criteria](https://www.palantir.com/docs/foundry/action-types/submission-criteria/))
- 주의: 제출 조건 불충족은 HTTP 200 + `validation: INVALID`. 화면에서 성공으로 처리하지 않는다 (PoC 관찰).

## Action ② 리비전 올리기

| 파라미터 | 형식 | 규칙 |
|---|---|---|
| 대상 객체 | 내부 엔티티 | 필수 |
| `target_src_rev_no` | 정수 | = HEAD.`src_rev_no`만 허용 (중간 rev 건너뛰기 없음) |
| `reason` | 문자열 | 필수. `{{사유 최소 길이}}` |
| `expected_work_version` | 정수 | 낙관적 잠금 |

함수가 하는 일:

1. HEAD를 다시 읽는다. 화면이 본 뒤 바뀌었으면 거부 ("원천이 또 바뀜. 차이를 다시 확인").
2. 배지 판정표대로 DELETE / OUT_OF_SCOPE 막기.
3. 내부 객체: `pinned_src_rev_no`, `pinned_rev_pk`, `pinned_by`, `pinned_at`, `work_version` 갱신.
4. PIN_HISTORY 1건 생성: 이전 rev, 새 rev, 사람, 시각, 사유.

- 제출 조건: `{{리비전 올리기 권한 그룹}}`. 내부 정보 편집 권한과 분리 (기능 권한).
- 하위 영향: 고정 rev를 쓰는 하위 계산(`{{하위 계산}}`)은 다음 빌드에서 바뀐다. 하위 파이프라인이 고정 rev를 읽으려면 내부 객체 materialization이 필요하다 (D3와 같은 방식). ([Materializations](https://www.palantir.com/docs/foundry/object-edits/materializations/))
- 확인 필요: 내부 리비전이 이미 잠긴 경우 고정 rev 변경을 막을지. → `{{잠금 후 변경 규칙}}`

## 권한

- REVISION · HEAD · RECEIPT · 내부 엔티티 · PIN_HISTORY 모두 `viewerGroupIds` 행 정책 (D30). 정책 없는 타입은 사용자에게 아무것도 안 보인다 (PoC 관찰). ([Object security policies](https://www.palantir.com/docs/foundry/object-permissioning/object-security-policies/))
- 사용자가 내부 객체는 보이는데 고정 REVISION은 안 보이면 영역 A가 빈다. 그래서 같은 `{{권한 단위}}` 기준으로 권한 값을 맞춘다. 확인 필요: 새 리비전 행에 권한 배정을 누가 하나 (D30 남은 과제).
- 필드 단위로 숨길 원천 필드가 있으면 `{{숨길 필드}}`. 방식은 확인 필요 (속성 단위 보안 기능이 6.550.1에 있는지).

## 테스트 시나리오

| # | 준비 | 동작 | 기대 |
|---|---|---|---|
| 1 | pinned = HEAD | 화면 열기 | 배지 없음, 올리기 버튼 숨김 |
| 2 | 원천 값 1개 바꾸고 빌드 | 화면 열기 | "새 리비전 있음", 차이 보기에 그 필드 1개 |
| 3 | 2 다음 | 리비전 올리기 (사유 입력) | pinned = HEAD, PIN_HISTORY 1건, 배지 사라짐 |
| 4 | 원천에서 행 삭제 후 빌드 | 화면 열기 | "원천에서 삭제됨", 영역 A는 고정 rev 값 그대로 |
| 5 | 사용자 2명 같은 화면 | 둘 다 내부 정보 저장 | 먼저 저장 성공, 나중 사람 충돌 메시지 |
| 6 | 화면 연 뒤 원천 또 바뀜 | 리비전 올리기 | 거부, "다시 확인" |
| 7 | 편집 권한 없는 사용자 | 화면 열기 | 조회만, 버튼 숨김. API로 Action 호출 → INVALID |
| 8 | 행 권한 없는 사용자 | 객체 URL 직접 열기 | 404 문구 |
| 9 | 리비전 transform 재빌드 | 화면 열기 | pinned 값·내부 값 그대로 |

## 기존 결정과 다른 점

| 기존 | 바뀜 | 이유 |
|---|---|---|
| D7: 내부는 `pinned_src_rev_no`만 가짐 | `pinned_rev_pk`, `head_pk` 문자열 FK 추가 | Link Type은 FK 1개 ↔ PK 1개. 조합 키로는 Link 불가 |
| D7: "리비전 올리기 = 담당자 Action" | 대상 rev = HEAD만, 사유 필수, PIN_HISTORY 객체로 이력 | 누가·왜 바꿨는지 화면에서 조회 |

## 보고서 반영할 것

- 결정 7 (D7) 아래에 "화면 연동: 고정 rev Link + HEAD Link, 리비전 올리기 Action ②" 한 줄.
- 리스크 목록: "비교 필드 설정이 D7 해시 목록과 따로 놀면 가짜 배지".

## 채울 것 (내부 AI)

| 빈칸 | 뜻 | 어디서 확인 | 모르면 사용자에게 |
|---|---|---|---|
| `{{내부 엔티티}}` | 화면의 주인 객체 | 우리 온톨로지 | "기본 정보 화면은 어느 Object Type의 화면인가?" |
| `{{내부 PK 규칙}}` | 내부 객체 PK | 기존 Object Type | "내부 객체 PK는 어떻게 만드나?" |
| `{{원천코드}}` | 원천 짧은 코드 | D7 설정 | "원천 약어는?" |
| `{{원천 표시 필드 목록}}` | 영역 A에 보일 원천 필드 | 원천 스키마 + 화면 기획 | "원천 필드 중 화면에 보일 것은?" |
| `{{내부 편집 필드 목록}}` / `{{형식}}` / `{{검증 규칙}}` | 영역 D 필드 | 화면 기획 | "우리가 직접 입력하는 기본 정보 필드와 규칙은?" |
| `{{원천 리비전 표시 형식}}` / `{{내부 리비전 표시 형식}}` | 화면 표시 | D7 남은 질문 1 | "원천 리비전을 S0처럼 보여도 되나?" |
| `{{삭제 시 처리}}` / `{{범위 밖 처리}}` | 그때 올리기 허용 여부 | 업무 규칙 | "원천에서 삭제되면 고정을 그대로 둘까, 따로 처리할까?" |
| `{{편집 권한 그룹}}` / `{{리비전 올리기 권한 그룹}}` | Action 제출 조건 | 권한 설계 (D6) | "누가 편집하고 누가 리비전을 올리나?" |
| `{{권한 단위}}` / `{{숨길 필드}}` | 행·필드 권한 기준 | 보안 가이드 | "행 권한 기준 단위는? 숨길 필드 있나?" |
| `{{사유 최소 길이}}` | 사유 검증 | - | "사유 최소 몇 자?" |
| `{{하위 계산}}` | 고정 rev를 쓰는 계산 | 파이프라인 | "고정 rev 바뀌면 다시 계산되는 것은?" |
| `{{잠금 후 변경 규칙}}` | 내부 리비전 잠긴 뒤 고정 변경 | 업무 규칙 | "내부 리비전이 잠긴 뒤에도 원천 rev를 올릴 수 있나?" |
