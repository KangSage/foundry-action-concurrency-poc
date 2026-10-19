# 최소 합성 PoC 설계: Scope + Receipt 단일 edit batch와 동시성

> 상태: 설계안 v2(미실행) · 2026-10-19
> 실제 조직의 데이터, 내부 식별자, 자격 증명을 **전혀 쓰지 않는** 합성 설계다.
> 모든 이름은 이 PoC 전용 합성 이름(`Syn*`)이다.

v2 변경 요약은 이렇다.

- 테스트 대상 Global Branch를 명시한다.
- 성공은 validation 결과와 같은 브랜치에서의 재조회로 판정한다.
- Action 동시성 설정을 고정한다.
- payload 해시는 함수가 직접 계산한다.
- Receipt PK를 `scopeKey + requestId`로 바꾼다.
- noop 경로와 write skew 실험을 추가한다.
- 경쟁 실험에 증거 채택 규칙을 둔다.
- Main 병합과 재시험은 범위에서 뺀다.

---

## 1. 확인할 질문과 판정 기준

| # | 질문 | "예"로 판정하는 증거 |
|---|------|------------------|
| Q1 | TS v2 Function-backed Action 하나에서 **고정 PK Scope**(생성/갱신)와 **요청별 Receipt**(생성)를 **한 edit batch**로 저장할 수 있는가? | (a) apply 응답의 validation 결과가 `VALID`다. (b) **같은 브랜치에서 다시 조회**하면 Scope와 Receipt가 모두 반영돼 있다. (c) batch의 한쪽 edit가 **실제로 실패한 것이 관측된** 경우, 다른 쪽도 반영되지 않았다. |
| Q2 | 같은 Scope에 대해 ① 동시 최초 생성 ② 오래된 기대버전 ③ 같은 요청 재시도 ④ noop과 갱신의 경쟁에서 **실제로** 무엇이 일어나는가? | 실험 E1–E5의 관측표와 §8 불변식 위반 여부. 증거는 §7의 채택 규칙을 통과한 run만 쓴다. |

HTTP 200이나 응답의 edits만으로는 성공을 판정하지 않는다. Apply Action API에서 200은 요청이 처리됐다는 뜻일 뿐이고, 실제 적용 여부는 응답 본문의 validation 결과가 나타낸다([Apply Action](https://www.palantir.com/docs/foundry/api/ontologies-v2-resources/actions/apply-action)).

### 미지수와 문서상 기대

공개 문서([Consistency guarantees](https://www.palantir.com/docs/foundry/action-types/consistency-guarantees/))의 내용은 다음과 같다.

- 스냅샷 격리(snapshot isolation)에서 충돌 검사는 **쓴(written) 객체 기준**이다.
- 읽기만 한 객체는 충돌을 일으키지 않는다. 그래서 write skew가 생길 수 있다.

아래 표의 "문서상 기대"는 이 내용에서 나온 가설이다. PoC는 이 가설이 실제로 그런지 확인한다.

| ID | 미지수 | 문서상 기대 | 가능한 관측 |
|----|-------|-----------|-----------|
| U1 | 한 함수가 두 객체 타입의 edit를 함께 반환할 수 있는가 | 가능 | 가능 / 불가 |
| U2 | 이미 존재하는 PK에 `create`가 적용되면 | 문서에 언급 없음 | 거부 / 덮어쓰기 |
| U3 | batch 일부가 적용 단계에서 실패하면 | 전체 롤백(원자적 적용) | 롤백 / 부분 반영 |
| U4 | 두 Action이 같은 Scope를 **쓰면** | 한쪽이 충돌 실패 | 충돌 실패 / 둘 다 성공(LWW) |
| U5 | noop 요청이 Scope는 읽기만 하고 Receipt만 쓸 때, 동시에 Scope 갱신이 커밋되면 | 둘 다 커밋됨(write skew) | write skew / 충돌 |
| U6 | U5에서 noop도 Scope를 강제로 쓰게 하면 | 한쪽이 충돌 실패 | 충돌 실패 / 둘 다 성공 |

---

## 2. 합성 환경

| 리소스 | 이름(예시) | 비고 |
|-------|-----------|-----|
| 프로젝트 | `Synthetic Concurrency PoC` | 다른 프로젝트와 공유 없음 |
| 백킹 데이터셋 2개 | `syn_scope_empty`, `syn_receipt_empty` | 헤더만 있는 빈 CSV. 데이터소스와 edit 간 충돌을 배제하고, 실험 중 데이터셋 재빌드도 하지 않는다 |
| 객체 타입 2개 | `SynScope`, `SynReceipt` | OSv2, 편집 허용 |
| Functions 리포 1개 | `syn-functions` (TS v2 템플릿) | 함수 1개 |
| Action 타입 1개 | `syn-commit` | Function-backed, 설정은 §3 |
| 테스트 사용자 1명 | 합성 계정 | 임시 토큰은 실행할 때만 env로 넣는다 |
| 하네스 | 로컬 Node 20 스크립트 | REST Actions/Objects API |

- **모든 개발과 시험은 하나의 Global Branch에서 한다.** 브랜치에서 적용한 Action edit는 Main으로 병합되지 않는다. 이 PoC는 Proposal 병합이나 Main 재시험을 하지 않는다.
- 브랜치 RID는 실행할 때 env로만 넣고, 저장소에 커밋하지 않는다.

---

## 3. Action 설정 고정 (시험 전후 확인)

Ontology Manager의 Capabilities에서 아래 값으로 고정한다. 각 실험 세션을 **시작하기 전과 끝난 뒤** 설정 화면을 다시 확인해서 기록한다. 설정이 바뀌어 있으면 그 세션의 결과는 폐기한다.

| 설정 | 값 | 이유 |
|-----|---|-----|
| Write mode | **Batched writes** | 스냅샷 격리를 쓰려면 필요하다 |
| Isolation level | **Snapshot isolation** | 쓴 객체 기준 충돌 검사(U4–U6)의 전제 |
| Retry mode on transient errors | **Disabled** | 자동 재시도가 켜져 있으면 충돌 실패가 재시도에 묻혀, 결과 해석이 달라진다 |

---

## 4. 객체 모델

### `SynScope` — 고정 PK

| 속성 | 타입 | 설명 |
|-----|-----|-----|
| `scopeKey` (PK) | String | run마다 정하는 결정적 상수. 예: `scope-e2-r1` |
| `value` | String | 요청이 설정하려는 값. 같으면 noop |
| `version` | Integer | 값이 바뀔 때만 +1 |
| `lastReceiptKey` | String | 마지막으로 Scope를 쓴 Receipt |
| `updatedAt` | Timestamp | 함수 측 시각 |

### `SynReceipt` — 요청별

| 속성 | 타입 | 설명 |
|-----|-----|-----|
| `receiptKey` (PK) | String | `{scopeKey}::{requestId}`. 입력에 `::`가 들어 있으면 거부한다 |
| `scopeKey`, `requestId` | String | |
| `outcome` | String | `APPLIED`(값 변경) / `NOOP`(이미 같은 값) |
| `observedVersion` | Integer | 함수가 읽은 Scope version(없으면 0) |
| `resultVersion` | Integer | APPLIED면 observed+1, NOOP이면 observed |
| `payloadHash` | String | **함수가** 정규화한 입력으로 계산한 값 |
| `writerTag` | String | 하네스 태그(A/B/…) |
| `readAt` / `emitAt` | Timestamp | 함수가 읽은 시각 / edit를 반환한 시각 |

PK를 `requestId` 하나가 아니라 `scopeKey + requestId`로 정한 이유: 서로 다른 Scope의 요청이 우연히 같은 requestId를 쓰더라도 충돌하지 않게 하려는 것이다.

---

## 5. Action / Function 설계

### 파라미터

| 파라미터 | 타입 | 용도 |
|---------|-----|-----|
| `scopeKey`, `requestId` | String | |
| `desiredValue` | String | 설정하려는 값 |
| `expectedVersion` | Integer | 클라이언트가 기대하는 현재 version(최초 생성이면 0) |
| `writerTag` | String | |
| `delayMs` | Integer | **테스트용.** 읽은 뒤 edit 반환 전에 대기한다(0–5000). 경쟁이 일어날 확률을 높이지만 경쟁을 보장하지는 않는다 |
| `skipIdempotencyCheck` | Boolean | **테스트용.** Receipt 존재 검사를 건너뛴다 |
| `failMode` | String | **테스트용.** `none` / `dupReceipt` / `updateMissingScope` |
| `noopTouchScope` | Boolean | **테스트용.** noop이어도 Scope에 `lastReceiptKey`/`updatedAt`을 쓴다(version은 그대로). U6용 |
| `editOrder` | String | **테스트용.** `scopeFirst` / `receiptFirst` |

### 함수 로직

```
0. 입력 검증(키에 "::" 금지)과 정규화(문자열 trim, 유니코드 NFC)
   payloadHash = sha256(canonicalJSON{ scopeKey, desiredValue, expectedVersion })
   requestId와 writerTag는 해시에 넣지 않는다
1. Receipt(receiptKey) 조회  (skipIdempotencyCheck면 생략)
   - 있고 해시 같음 → edits [] 반환 (멱등 성공 후보, §7 판정 참조)
   - 있고 해시 다름 → 에러 REQUEST_ID_REUSED
2. Scope(scopeKey) 조회 → observedVersion, observedValue, readAt
3. observedVersion != expectedVersion → 에러 STALE
4. sleep(delayMs)
5. Scope가 있고 observedValue == desiredValue (NOOP):
     create Receipt{outcome: NOOP, resultVersion: observed}
     noopTouchScope면 update Scope{lastReceiptKey, updatedAt}
   그 밖 (APPLIED):
     Scope가 없으면 create, 있으면 update {value, version: observed+1, lastReceiptKey}
     create Receipt{outcome: APPLIED, resultVersion: observed+1}
   failMode와 editOrder를 반영
6. edits 반환 (emitAt)
```

- `expectedVersion`이 해시에 들어가므로, 기대버전을 바꾼 재시도는 **새 requestId**로 보내야 한다(E4e).
- TS v2 API 이름(`createEditBatch`, `fetchOneWithErrors`, `Integer`)과 함수 런타임의 `crypto` 사용 가능 여부는 E0 빌드에서 확정한다.

---

## 6. 하네스

- 모든 호출에 `?branch=<브랜치 RID>`를 붙인다. apply, 단건 조회, search 모두 해당한다. **브랜치 env가 없으면 하네스는 실행을 거부한다.** 생략하면 기본 브랜치로 갈 수 있기 때문이다.
- 호출: `POST /api/v2/ontologies/{ontology}/actions/syn-commit/apply?branch=…`, `options: { mode: "VALIDATE_AND_EXECUTE", returnEdits: "ALL" }`
- 요청마다 기록하는 것: HTTP status, validation 결과, 에러 이름과 분류(충돌 실패 여부 포함), 응답 edits, 클라이언트 `sentAt`/`doneAt`. JSONL로 저장하고 커밋하지 않는다.
- **판정은 같은 브랜치에서 다시 조회한 결과로 한다.** 대상은 Scope 단건과, `scopeKey`로 필터한 Receipt 목록이다. 응답 edits는 참고용으로만 본다.
- run마다 새 `scopeKey`를 쓰고, 각 실험을 5회 반복한다.

---

## 7. 실험과 증거 채택 규칙

### 증거 채택 규칙

- **경쟁 실험(E2b, E3b, E4c, E5):** 실제로 경쟁이 일어났을 때만 채택한다. 조건은 B의 커밋 완료(B의 `doneAt`)가 A의 `readAt` 이후이면서 A의 `doneAt` 이전인 것이다. 이 조건이 확인되지 않으면 **"경쟁 미성립"으로 표시하고, 합격과 불합격 어느 쪽의 근거로도 쓰지 않는다.**
- **충돌이 관측되지 않음**은 "충돌이 없다"는 증거가 아니다.
- **강제 실패(E1):** apply 결과가 실제로 실패로 관측된 run만 원자성 근거로 쓴다. `dupReceipt`와 `updateMissingScope` 둘 다 실패를 만들지 못하면 Q1의 원자성은 **판정 보류**다.
- **멱등 성공:** 같은 요청을 재시도했을 때 세 가지를 모두 만족해야 한다. ① validation이 `VALID` ② 새 edit가 0건 ③ 재조회 결과 Receipt가 1건 그대로이고 Scope도 그대로. 재시도가 PK 중복으로 **거부되는 것은 "중복 차단"이지 멱등 성공이 아니다.**

### 실험 매트릭스

| ID | 목적 | 절차 | 관측 포인트 |
|----|-----|-----|-----------|
| **E0** | Q1 기본, U1 | 새 scope에서 생성(v0→1), 갱신(v1→2), 같은 값으로 noop(v2 유지) | 세 경로 모두 validation 결과와 재조회가 일치하는지 |
| **E1** | Q1 원자성, U3 | (a) Receipt를 먼저 만든 뒤 `skipIdempotencyCheck=true`로 같은 키를 다시 생성하면서 Scope도 갱신 (b) `failMode=updateMissingScope` (c) 각각 `editOrder` 2가지 | 실패가 실제로 관측됐는지, 관측됐다면 Scope가 그대로이고 Receipt가 없는지. (a)는 U2 결과에 따라 실패원이 되지 않을 수도 있다 |
| **E2** | ① 동시 최초 생성, U2/U4 | (a) 새 scope에 K=10 병렬, 서로 다른 requestId, `expectedVersion=0` (b) A(`delayMs=3000`), 500ms 뒤 B | 성공 수, 실패 분류, 최종 version, APPLIED Receipt 수 |
| **E3** | ② 오래된 기대버전, U4 | (a) 단순: v=3인 scope에 `expectedVersion=1` → STALE (b) 경쟁: A(delay, expected=n, 값 X→Y)와 B(expected=n, 값 X→Z) | (b): 경쟁이 성립한 run에서 한쪽이 충돌 실패하는지, 둘 다 성공(lost update)하는지 |
| **E4** | ③ 같은 요청 재시도 | (a) 성공 후 같은 요청 재전송 (b) 같은 requestId로 K=5 병렬 (c) (b)에 `delayMs` 추가 (d) 같은 requestId, 다른 `desiredValue` → REQUEST_ID_REUSED (e) STALE로 실패한 요청을 갱신된 expectedVersion과 **새 requestId**로 재시도 | (a)는 멱등 성공 3조건을 충족하는지. (b)(c)는 Receipt 1건, version +1만인지, 나머지가 멱등 성공인지 중복 차단인지 구분 |
| **E5** | ④ noop과 갱신의 경쟁, U5/U6 | Scope 값=X, v=n에서 A: `desiredValue=X`(noop), delay. B: `desiredValue=Y`. 둘 다 expected=n. (a) `noopTouchScope=false` (b) `noopTouchScope=true` | (a) A의 NOOP Receipt와 B의 APPLIED가 둘 다 커밋되는지(write skew). (b) 한쪽이 충돌 실패로 바뀌는지 |
| E6 (조건부) | 보완책 | U4가 "둘 다 성공"이고 U2가 "거부"일 때만: `SynVersionSlot`(PK=`{scopeKey}#{n}`)을 batch에 추가하고 E3b를 다시 실행 | slot PK 충돌로 CAS가 되는지 |

---

## 8. 불변식 (매 run 재조회 후 검사)

| ID | 불변식 | 위반이 의미하는 것 |
|----|-------|---------------|
| I1 | `Scope.version == count(Receipt where scopeKey, outcome=APPLIED)` (NOOP Receipt는 세지 않는다) | lost update, 또는 고아 Scope/Receipt |
| I2 | APPLIED Receipt의 `resultVersion` 집합 = {1..version}, 중복 없음 | 같은 version을 두 요청이 차지함 |
| I3 | 실패한 요청의 `receiptKey`로는 Receipt가 없음 | 부분 반영 |
| I4 | `receiptKey`당 Receipt ≤ 1, 재시도로 version이 다시 오르지 않음 | 멱등성 위반 |
| I5 | NOOP Receipt(resultVersion=r)가 커밋되기 **전에** `resultVersion=r+1`인 APPLIED가 이미 커밋돼 있지 않음 | write skew: noop이 오래된 값을 근거로 커밋됨 |

결과표 컬럼: `실험 · run · 경쟁 성립 여부 · K · 성공 수 · 실패 수(분류별) · 최종 value/version · APPLIED/NOOP Receipt 수 · I1–I5 · 설정 확인(전/후)`

---

## 9. 결과 해석 → 설계 함의

| 관측 | 함의 |
|-----|-----|
| U1 가능 + U3 롤백(실패 관측됨) | **Q1 = 예.** Scope와 Receipt를 한 Action에서 원자적으로 저장해도 된다 |
| E1에서 실패를 만들지 못함 | Q1 원자성은 판정 보류. 다른 실패원을 찾아야 한다 |
| U4 충돌 실패 | 같은 Scope를 쓰는 요청은 플랫폼이 직렬화한다. 클라이언트는 충돌 실패를 받으면 재조회하고 **새 requestId**로 재시도한다 |
| U4 둘 다 성공 | lost update. U2가 거부라면 E6 slot 패턴으로 보완하고, 아니라면 단일 작성자 직렬화가 필요하다 |
| U5 write skew | **noop이 Receipt만 쓰는 설계는 위험하다.** noop 판정을 근거로 한 Receipt가 이미 바뀐 값 위에 남는다 |
| U6 충돌 실패 | noop에서도 Scope를 쓰는 것(touch)으로 write skew를 막을 수 있다. 대가는 noop 사이의 충돌 증가 |
| U2 거부 | 중복 생성은 막힌다. 그러나 멱등 성공은 함수의 Receipt 조회 경로(E4a)로만 증명된다 |

---

## 10. 실행 순서와 사용자 확인 지점

1. 🔒 **사용자 승인:** 합성 프로젝트, 빈 데이터셋 2개, 객체 타입 2개, Functions 리포 생성.
2. Global Branch에서 객체 타입, 함수, Action을 만들고 §3 설정을 고정한다. E0 빌드로 API 이름을 확정한다.
3. 🔒 **사용자:** 합성 테스트 사용자의 임시 토큰과 브랜치 RID를 터미널 env에 넣는다(저장소에 커밋하지 않음).
4. 같은 브랜치에서 E0 → E5를 각 5회 실행한다. 세션 전후에 §3 설정을 확인한다.
5. 결과를 보고한다: Q1 판정(또는 보류), Q2 관측표, §9 함의. 필요하면 E6를 실행한다.
6. 🔒 **사용자:** 임시 토큰을 폐기한다. 브랜치와 합성 리소스를 보관할지 삭제할지 결정한다.

## 11. 범위 밖과 한계

- 범위 밖: Main 병합과 재시험, `applyBatch` API, 함수 batched execution, Staged writes, Read committed 격리, Automate/웹훅, OSv1, 다중 Scope 트랜잭션.
- 결과는 **이 브랜치와 이 설정(§3)에서만** 유효하다. API 문서에는 브랜치 지원이 실험적(experimental)이라고 적혀 있다.
- 동시성 결과는 비결정적이다. §7 채택 규칙을 통과한 run만 근거로 쓴다.
- 개발자 티어에서의 측정이 다른 enrollment나 티어에서도 같다는 보장은 없다.

## 참고 문서

- [Action types: Consistency guarantees](https://www.palantir.com/docs/foundry/action-types/consistency-guarantees/)
- [API: Apply Action](https://www.palantir.com/docs/foundry/api/ontologies-v2-resources/actions/apply-action)
