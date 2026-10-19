# 최소 합성 PoC 설계: Scope + Receipt 단일 edit batch와 동시성

> 상태: 설계안(미실행) · 작성 2026-10-19
> 실제 조직의 데이터, 내부 식별자, 자격 증명을 **전혀 쓰지 않는** 합성 설계다.
> 모든 이름은 이 PoC 전용 합성 이름(`Syn*`)이다.

---

## 1. 확인할 질문과 판정 기준

| # | 질문 | "예"로 판정하는 증거 |
|---|------|------------------|
| Q1 | TS v2 Function-backed Action 하나에서 **고정 PK Scope**(생성 또는 갱신)와 **요청별 Receipt**(생성)를 **한 edit batch**로 반환·저장할 수 있는가? | (a) apply 응답의 edits에 두 타입이 모두 나온다. (b) 직후 조회에서 두 객체가 모두 반영돼 있다. (c) batch의 한쪽 edit를 일부러 실패시키면 **다른 쪽도 반영되지 않는다**(원자성). |
| Q2 | 같은 Scope에 대해 ① 동시 최초 생성 ② 오래된 기대버전(stale expectedVersion) ③ 같은 요청 재시도에서 **실제로** 무엇이 일어나는가? | 실험 E2–E5의 관측값(HTTP 상태, 에러 이름, 성공 수, 최종 version, Receipt 수)과 §6 불변식의 위반 여부. |

Q2는 "예/아니오"가 아니라 **관측 결과 표**가 답이다. 결과에 따라 §7에서 설계 함의를 고른다.

### 확인해야 할 미지수

| ID | 미지수 | 가능한 결과 |
|----|-------|-----------|
| U1 | 한 함수가 서로 다른 두 객체 타입의 edit를 함께 반환할 수 있는가 | 가능 / 불가 |
| U2 | 이미 존재하는 PK에 `create` edit가 적용될 때 | **거부**(에러) / **덮어쓰기**(upsert) |
| U3 | batch 일부 edit가 적용 단계에서 실패할 때 | **전체 롤백** / 부분 반영 |
| U4 | 함수가 읽은 뒤 다른 요청이 같은 객체를 먼저 바꿨을 때(TOCTOU) | 플랫폼이 **충돌 에러** / **조용히 last-write-wins** |
| U5 | apply 응답 직후 조회가 새 값을 보이는가 | 즉시 / 지연(ms 단위 측정) |

---

## 2. 합성 환경 (새로 만드는 것만)

| 리소스 | 이름(예시) | 비고 |
|-------|-----------|-----|
| 프로젝트 | `Synthetic Concurrency PoC` | 다른 프로젝트와 공유 없음 |
| 백킹 데이터셋 2개 | `syn_scope_empty`, `syn_receipt_empty` | 헤더만 있는 빈 CSV. 데이터소스와 edit 간 충돌을 원천 배제하려는 목적 |
| 객체 타입 2개 | `SynScope`, `SynReceipt` | OSv2, 편집 허용 |
| Functions 리포 1개 | `syn-functions` (TS v2 템플릿) | 함수 1개 |
| Action 타입 1개 | `syn-commit` | Function-backed |
| 테스트 사용자 1명 | 합성 계정 | 실행할 때만 임시 토큰을 env로 넣고, 문서·코드에 저장하지 않음 |
| 하네스 | 로컬 Node 20 스크립트 | REST Actions API 호출 |

작업은 Global Branch에서 진행한다. 다만 **브랜치에서의 동시성 동작이 Main과 같다는 보장은 없다.** 그래서 브랜치에서 1차 측정을 하고, 병합한 뒤 Main에서 E2–E5를 다시 돌려 비교한다(사용자 승인 후).

---

## 3. 객체 모델

### `SynScope` — 고정 PK, 버전 카운터

| 속성 | 타입 | 설명 |
|-----|-----|-----|
| `scopeKey` (PK) | String | 실행(run)마다 결정적 상수. 예: `scope-e2-r1` |
| `version` | Integer | 커밋마다 +1 |
| `lastRequestId` | String | 마지막으로 반영된 요청 |
| `lastWriterTag` | String | 마지막 작성자 태그 |
| `updatedAt` | Timestamp | 함수 측 시각 |

### `SynReceipt` — 요청별, PK = requestId

| 속성 | 타입 | 설명 |
|-----|-----|-----|
| `requestId` (PK) | String | 클라이언트가 만든 멱등 키. 예: `e4-r1-a` |
| `scopeKey` | String | 대상 Scope |
| `observedVersion` | Integer | 함수가 **읽은** Scope version(없으면 0) |
| `appliedVersion` | Integer | 이 요청이 기록한 version(= observed + 1) |
| `payloadHash` | String | 같은 requestId에 다른 payload가 오면 감지하는 용도 |
| `writerTag` | String | 하네스가 붙이는 태그(A/B/…) |
| `readAt` / `emitAt` | Timestamp | 함수가 읽은 시각 / edit를 반환한 시각 |

Receipt PK를 requestId로 둔 이유: U2가 "거부"라면 **플랫폼의 PK 유일성 자체가 멱등 키 역할**을 한다. 이 PoC가 검증하려는 핵심 가설이다.

---

## 4. Action / Function 설계

### Action `syn-commit` 파라미터

| 파라미터 | 타입 | 용도 |
|---------|-----|-----|
| `scopeKey` | String | |
| `requestId` | String | |
| `expectedVersion` | Integer | 클라이언트가 기대하는 현재 version(최초 생성은 0) |
| `payloadHash` | String | |
| `writerTag` | String | |
| `delayMs` | Integer | **테스트용.** 읽은 뒤 edit 반환 전에 대기해서 경쟁 구간을 결정적으로 벌린다(0–5000) |
| `skipIdempotencyCheck` | Boolean | **테스트용.** 함수 단계의 Receipt 존재 검사를 건너뛰고, 플랫폼 단계(U2)를 직접 시험한다 |
| `failMode` | String | **테스트용.** `none` / `dupReceipt` / `updateMissingScope` |
| `editOrder` | String | **테스트용.** `scopeFirst` / `receiptFirst` |

### 함수 로직 (의사코드)

```
1. receipt = Receipt(requestId) 조회
   - 있고 payloadHash 같음  → edits [] 반환 (멱등 no-op)
   - 있고 payloadHash 다름  → UserFacing 에러 "requestId 재사용"
   (skipIdempotencyCheck=true면 1단계 생략)
2. scope = Scope(scopeKey) 조회 → observed = scope?.version ?? 0, readAt = now
3. observed != expectedVersion → UserFacing 에러 "stale: expected X, observed Y"
4. sleep(delayMs)
5. edits:
   - scope 없음 → create Scope{version:1}
   - scope 있음 → update Scope{version: observed+1}
   - create Receipt{requestId, observedVersion: observed, appliedVersion: observed+1, ...}
   - failMode=updateMissingScope → Scope 대신 존재하지 않는 PK에 update
   - editOrder에 따라 순서 조정
6. edits 반환 (emitAt = now)
```

3단계 검사는 **함수가 읽은 시점** 기준이다. 4–5단계 사이에 다른 요청이 커밋하면 이 검사로는 막을 수 없다. 이 틈(U4)을 실험으로 드러내는 것이 `delayMs`의 목적이다.

### TS v2 스케치 (API 이름은 E0에서 컴파일로 확정)

```ts
import type { Client } from "@osdk/client";
import { createEditBatch, type Edits, type Integer } from "@osdk/functions";
import { SynScope, SynReceipt } from "@syn-poc/sdk";

type OntologyEdit = Edits.Object<SynScope> | Edits.Object<SynReceipt>;

async function synCommit(
  client: Client,
  scopeKey: string,
  requestId: string,
  expectedVersion: Integer,
  payloadHash: string,
  writerTag: string,
  delayMs: Integer,
  skipIdempotencyCheck: boolean,
  failMode: string,
  editOrder: string,
): Promise<OntologyEdit[]> {
  const batch = createEditBatch<OntologyEdit>(client);
  // 1–3: fetchOneWithErrors 로 Receipt/Scope 조회, 검사, 실패 시 throw
  // 4: await new Promise(r => setTimeout(r, delayMs));
  // 5: batch.create(SynScope, {...}) 또는 batch.update({ $apiName: "SynScope", $primaryKey: scopeKey }, {...})
  //    batch.create(SynReceipt, {...})
  return batch.getEdits();
}
export default synCommit;
```

---

## 5. 하네스와 실험

### 하네스

- `POST /api/v2/ontologies/{ontology}/actions/syn-commit/apply`를 `options: { mode: "VALIDATE_AND_EXECUTE", returnEdits: "ALL" }`로 호출한다.
- 동시 호출은 요청 객체를 미리 다 만들어 두고 `Promise.all`로 한꺼번에 발사한다. 클라이언트 측 `sentAt`/`doneAt`을 기록한다.
- 각 요청마다 HTTP status, `errorCode`/`errorName`(원문 그대로), 응답 edits를 JSONL로 저장한다.
- 사후 검증은 Scope 단건 조회와 `scopeKey`로 필터한 Receipt search로 한다. 즉시 1회 조회하고, 값이 안정될 때까지 최대 10초 폴링해서 U5를 측정한다.
- run마다 새 `scopeKey`를 쓰고 같은 실험을 **5회 반복**해서 결과 분포를 기록한다.

### 실험 매트릭스

| ID | 목적 | 절차 | 기대/관측 포인트 |
|----|-----|-----|---------------|
| **E0** | Q1 기본, U1, U5 | 새 scope에 1회 호출(v0→1), 다시 1회 호출(v1→2) | 두 타입 edit가 함께 반영되는지, 생성과 갱신 경로 모두. 즉시 조회 일관성 |
| **E1** | Q1 원자성, U3 | (a) Receipt `X`를 먼저 만들고, `skipIdempotencyCheck=true, requestId=X`로 호출해 Scope 갱신과 Receipt 중복 생성을 함께 시도 (b) `failMode=updateMissingScope` (c) 각각 `editOrder` 2가지 | 실패 시 **Scope.version이 그대로인지**, Receipt가 생기지 않았는지. U2가 "덮어쓰기"로 나오면 (a)는 실패원이 안 되므로 (b)로 판정 |
| **E2** | ② 동시 최초 생성, U2 | (a) 새 scope에 K=10 병렬, 서로 다른 requestId, `expectedVersion=0` (b) 결정적 경쟁: A(`delayMs=3000`) 발사, 500ms 뒤 B(`delayMs=0`) 발사 | 성공 수, 에러 이름, 최종 version, Receipt 수. (b)에서 A의 `create Scope`가 거부되는지 덮어쓰는지 |
| **E3** | 오래된 기대버전, U4 | (a) 단순: v=3인 scope에 `expectedVersion=1`로 호출 (b) 결정적 경쟁: A(delay 3000, expected=n) 발사, 500ms 뒤 B(expected=n) 발사. B가 먼저 커밋한 뒤 A가 edit 반환 | (a)는 함수 에러가 기대 결과. (b)가 핵심: A가 **성공하면 lost update**(두 Receipt의 observedVersion이 같음), 실패하면 플랫폼 OCC 존재 |
| **E4** | ③ 같은 요청 재시도 | (a) 성공 후 같은 요청 재전송 (b) 같은 requestId로 K=5 병렬 (c) (b)를 `delayMs=3000`으로 경쟁 구간을 확대 (d) 같은 requestId, 다른 payloadHash (e) stale로 실패한 요청을 expected를 갱신해 재시도 | (a) no-op 성공, version 불변 (b)(c) Receipt 1개, version +1만, 나머지는 no-op 또는 PK 충돌 에러 (d) 거부 (e) 정상 반영 |
| **E5** | 혼합 부하 | 기존 scope에 K=20 병렬, 서로 다른 requestId, 모두 같은 `expectedVersion` | 성공 수 = version 증가분인지, 성공이 2건 이상이면 lost update |
| E6 (선택) | 보완책 검증 | U2=거부, U3=롤백일 때만: 3번째 타입 `SynVersionSlot`(PK=`{scopeKey}#{n}`)을 batch에 추가해 E3(b)·E5를 다시 실행 | slot PK 충돌로 진짜 CAS가 되는지 |

---

## 6. 불변식 (매 run 사후 검사)

| ID | 불변식 | 위반이 의미하는 것 |
|----|-------|---------------|
| I1 | `Scope.version == count(Receipt where scopeKey)` | lost update, 또는 고아 Receipt/Scope 증가 |
| I2 | Receipt의 `appliedVersion` 집합 = {1..version}, 중복 없음 | 같은 version을 두 요청이 차지함(lost update) |
| I3 | 실패한 요청의 requestId로는 Receipt가 없음 | 부분 반영(원자성 위반) |
| I4 | requestId당 Receipt ≤ 1, 같은 requestId 재시도로 version이 두 번 오르지 않음 | 멱등성 위반 |

결과표 컬럼: `실험 · run · K · 성공 수 · 실패 수(에러 이름별) · 최종 version · Receipt 수 · I1–I4 · 즉시조회 일치 여부 · 안정화 ms`

---

## 7. 결과 해석 → 설계 함의

| 관측 | 함의 |
|-----|-----|
| U1 가능 + U3 전체 롤백 | **Q1 = 예.** Scope와 Receipt를 한 Action에서 원자적으로 저장하는 패턴을 써도 된다 |
| U3 부분 반영 | Q1 = 아니오(원자성 없음). Receipt를 커밋 증거로 쓸 수 없으므로 보정 작업이 필요하다 |
| U2 거부 | Receipt PK(requestId)가 **플랫폼 강제 멱등 키**가 된다. 동시 최초 생성은 1건만 성공한다 |
| U2 덮어쓰기 | 플랫폼 유일성이 없다. 멱등과 최초 생성 보장은 함수 단계의 best-effort뿐이다 |
| U4 충돌 에러 | `expectedVersion`과 플랫폼 OCC로 충분하다. 클라이언트는 충돌 에러에서 재조회 후 재시도하면 된다 |
| U4 조용한 LWW | 함수 안의 expectedVersion 검사는 **TOCTOU 구간(함수 실행 시간)만큼 뚫린다.** U2가 거부라면 E6 slot 패턴으로 보완하고, 아니라면 단일 작성자 직렬화가 필요하다(별도 PoC) |
| U5 지연 | 클라이언트는 apply 응답의 edits를 진실로 쓰고, 직후 조회 값에 의존하지 않는다 |

---

## 8. 실행 순서와 사용자 확인 지점

1. 🔒 **사용자 승인:** 합성 프로젝트, 빈 데이터셋 2개, 객체 타입 2개, Functions 리포 생성. 리소스 *생성*은 브랜치에서 해도 Main에 영향이 있다.
2. Global Branch에서 객체 타입 2개, 함수, Action을 만든다. E0 컴파일로 API 이름을 확정한다.
3. 🔒 **사용자:** 합성 테스트 사용자의 임시 토큰을 발급해 터미널 env에 넣는다(토큰은 저장소에 커밋하지 않음).
4. 브랜치에서 E0 → E1 → E2 → E3 → E4 → E5를 각 5회 실행하고, 결과표와 불변식을 기록한다.
5. 🔒 **사용자 승인:** Proposal 생성과 병합. 이후 Main에서 E2–E5를 다시 측정하고 브랜치 결과와 비교한다.
6. 결과 보고: Q1 판정, Q2 관측표, §7 함의. 필요하면 E6를 추가로 진행한다.
7. 🔒 **사용자:** 임시 토큰을 폐기한다. 합성 리소스는 보관할지 삭제할지 결정한다.

## 9. 범위 밖과 한계

- 범위 밖: `applyBatch` API, Automate/웹훅, OSv1, 백킹 데이터셋 갱신과 사용자 edit 사이의 충돌 해결 전략(데이터셋은 비워 둠), 다중 Scope 트랜잭션.
- 동시성 결과는 비결정적이다. "충돌이 관측되지 않음"은 증명이 아니다. 그래서 `delayMs`로 만든 **결정적 경쟁**(E2b, E3b, E4c)의 결과를 1차 근거로 삼는다.
- 개발자 티어에서 측정한 결과가 다른 등록(enrollment)이나 티어에서도 같다는 보장은 없다. 보고서에 측정 환경을 명시한다.
