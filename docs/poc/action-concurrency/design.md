# 최소 합성 PoC 설계: Scope + Receipt 단일 edit batch와 동시성

> 상태: 설계안 v3(미실행) · 2026-10-19
> 실제 조직의 데이터, 내부 식별자, 자격 증명을 **전혀 쓰지 않는** 합성 설계다.
> 모든 이름은 이 PoC 전용 합성 이름(`Syn*`)이다.
> 실행 범위: 개인 dev tier, **하나의 Global Branch 안에서만** 실행한다.

### v3 변경 요약

- **순서 증거:** 경쟁 순서는 클라이언트 시각이 아니라 **중간 브랜치 조회**로 증명한다. 증명할 수 없는 run은 보류한다.
- **금지 동작 명시:** 금지 동작 F1/F2를 정의하고, F1(write skew)은 E5의 순서 관측으로 검사한다.
- **실행 통제:** 승인 단계를 리소스 생성 / 게시·생성 / 실제 apply로 나누고, apply 전 점검표와 호출 상한을 둔다.
- **writerTag:** 진단값으로 명시하고, 결과와 해시에 영향을 주지 않게 한다.

---

## 1. 확인할 질문과 판정 기준

| # | 질문 | "예"로 판정하는 증거 |
|---|------|------------------|
| Q1 | TS v2 Function-backed Action 하나에서 **고정 PK Scope**(생성/갱신)와 **요청별 Receipt**(생성)를 **한 edit batch**로 저장할 수 있는가? | (a) apply 응답의 validation 결과가 `VALID`다. (b) **같은 브랜치에서 다시 조회**하면 Scope와 Receipt가 모두 반영돼 있다. (c) batch의 한쪽 edit가 **실제로 실패한 것이 관측된** 경우, 다른 쪽도 반영되지 않았다. |
| Q2 | 같은 Scope에 대해 ① 동시 최초 생성 ② 오래된 기대버전 ③ 같은 요청 재시도 ④ noop과 갱신의 경쟁에서 **실제로** 무엇이 일어나고, 금지 동작(§8)이 발생하는가? | 실험 E1–E5의 관측표. 증거는 §7의 채택 규칙을 통과한 run만 쓴다. |

HTTP 200이나 응답의 edits만으로는 성공을 판정하지 않는다. Apply Action API에서 200은 요청이 처리됐다는 뜻일 뿐이고, 실제 적용 여부는 응답 본문의 validation 결과가 나타낸다([Apply Action](https://www.palantir.com/docs/foundry/api/ontologies-v2-resources/actions/apply-action)).

### 미지수와 문서상 기대

공개 문서([Consistency guarantees](https://www.palantir.com/docs/foundry/action-types/consistency-guarantees/))의 내용은 다음과 같다.

- 스냅샷 격리에서 충돌 검사는 **쓴(written) 객체 기준**이다.
- 읽기만 한 객체는 충돌을 일으키지 않는다. 그래서 write skew가 생길 수 있다.

아래 "문서상 기대"는 이 내용에서 나온 가설이고, PoC는 이 가설을 확인한다.

| ID | 미지수 | 문서상 기대 | 가능한 관측 |
|----|-------|-----------|-----------|
| U1 | 한 함수가 두 객체 타입의 edit를 함께 반환할 수 있는가 | 가능 | 가능 / 불가 |
| U2 | 이미 존재하는 PK에 `create`가 적용되면 | 문서에 언급 없음 | 거부 / 덮어쓰기 |
| U3 | batch 일부가 적용 단계에서 실패하면 | 전체 롤백 | 롤백 / 부분 반영 |
| U4 | 두 Action이 같은 Scope를 **쓰면** | 한쪽이 충돌 실패 | 충돌 실패 / 둘 다 성공 |
| U5 | noop 요청이 Scope는 읽기만 하고 Receipt만 쓰는데, 그 사이 Scope 갱신이 커밋되면 | noop도 커밋됨(write skew) | write skew / 충돌 |
| U6 | U5에서 noop도 Scope를 강제로 쓰게 하면 | 한쪽이 충돌 실패 | 충돌 실패 / 둘 다 성공 |

---

## 2. 합성 환경

| 리소스 | 이름(예시) | 비고 |
|-------|-----------|-----|
| 프로젝트 | `Synthetic Concurrency PoC` | 다른 프로젝트와 공유 없음 |
| 백킹 데이터셋 2개 | `syn_scope_empty`, `syn_receipt_empty` | 헤더만 있는 빈 CSV. 실험 중 재빌드하지 않는다 |
| 객체 타입 2개 | `SynScope`, `SynReceipt` | OSv2, 편집 허용 |
| Functions 리포 1개 | `syn-functions` (TS v2 템플릿) | 함수 1개, 외부 호출 없음 |
| Action 타입 1개 | `syn-commit` | Function-backed, 설정은 §3 |
| 테스트 사용자 1명 | 합성 계정 | 임시 토큰은 실행할 때만 env로 넣는다 |
| 하네스 | 로컬 Node 20 스크립트 | REST Actions/Objects API |

- **모든 개발과 시험은 하나의 Global Branch에서 한다.** 브랜치에서 적용한 Action edit는 Main으로 병합되지 않는다. Proposal 병합과 Main 시험은 하지 않는다.
- 브랜치 RID는 실행할 때 env로만 넣고, 저장소에 커밋하지 않는다.

---

## 3. Action 설정 고정

Ontology Manager의 Capabilities에서 아래 값으로 고정한다. 실험 세션을 **시작하기 전과 끝난 뒤** 설정을 다시 확인해서 기록한다. 설정이 바뀌어 있으면 그 세션의 결과는 폐기한다.

| 설정 | 값 | 이유 |
|-----|---|-----|
| Write mode | **Batched writes** | 스냅샷 격리를 쓰려면 필요하다 |
| Isolation level | **Snapshot isolation** | 쓴 객체 기준 충돌 검사(U4–U6)의 전제 |
| Retry mode on transient errors | **Disabled** | 자동 재시도가 충돌 실패를 가리면 결과 해석이 달라진다 |

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
| `writerTag` | String | **진단값.** 하네스 태그(A/B/…). 해시와 판정에 쓰지 않는다 |
| `readAt` / `emitAt` | Timestamp | **진단값.** 순서 증거로 쓰지 않는다(§7) |

PK를 `scopeKey + requestId`로 정한 이유: 서로 다른 Scope의 요청이 우연히 같은 requestId를 쓰더라도 충돌하지 않게 하려는 것이다.

`writerTag`의 성질: 같은 요청을 재시도하면서 `writerTag`만 다르게 보내도 멱등 성공으로 처리한다. 저장된 Receipt의 `writerTag`는 첫 커밋 값 그대로 남는다.

---

## 5. Action / Function 설계

### 파라미터

| 파라미터 | 타입 | 용도 |
|---------|-----|-----|
| `scopeKey`, `requestId` | String | |
| `desiredValue` | String | 설정하려는 값 |
| `expectedVersion` | Integer | 클라이언트가 기대하는 현재 version(최초 생성이면 0) |
| `writerTag` | String | 진단값(§4) |
| `delayMs` | Integer | **테스트용.** 읽은 뒤 edit 반환 전에 대기한다(0–5000). 중간 조회를 끼워 넣을 시간을 만들 뿐, 경쟁을 보장하지는 않는다 |
| `skipIdempotencyCheck` | Boolean | **테스트용.** Receipt 존재 검사를 건너뛴다 |
| `failMode` | String | **테스트용.** `none` / `dupReceipt` / `updateMissingScope` |
| `noopTouchScope` | Boolean | **테스트용.** noop이어도 Scope에 `lastReceiptKey`/`updatedAt`을 쓴다(version은 그대로). U6용 |
| `editOrder` | String | **테스트용.** `scopeFirst` / `receiptFirst` |

### 함수 로직

```
0. 입력 검증(키에 "::" 금지)과 정규화(문자열 trim, 유니코드 NFC)
   payloadHash = sha256(canonicalJSON{ scopeKey, desiredValue, expectedVersion })
   requestId, writerTag, 테스트용 파라미터는 해시에 넣지 않는다
1. Receipt(receiptKey) 조회  (skipIdempotencyCheck면 생략)
   - 있고 해시 같음 → edits [] 반환 (멱등 성공 후보, §7)
   - 있고 해시 다름 → 에러 REQUEST_ID_REUSED
2. Scope(scopeKey) 조회 → observedVersion, observedValue
3. observedVersion != expectedVersion → 에러 STALE(observed=…)
   관측한 version을 에러 메시지에 넣어서, 실패한 요청의 관측값도 남긴다
4. sleep(delayMs)
5. Scope가 있고 observedValue == desiredValue (NOOP):
     create Receipt{outcome: NOOP, resultVersion: observed}
     noopTouchScope면 update Scope{lastReceiptKey, updatedAt}
   그 밖 (APPLIED):
     Scope가 없으면 create, 있으면 update {value, version: observed+1, lastReceiptKey}
     create Receipt{outcome: APPLIED, resultVersion: observed+1}
   failMode와 editOrder를 반영
6. edits 반환
```

- `expectedVersion`이 해시에 들어가므로, 기대버전을 바꾼 재시도는 **새 requestId**로 보내야 한다(E4e).
- TS v2 API 이름(`createEditBatch`, `fetchOneWithErrors`, `Integer`)과 함수 런타임의 `crypto` 사용 가능 여부는 E0 빌드에서 확정한다.

---

## 6. 하네스

- 모든 호출에 `?branch=<브랜치 RID>`를 붙인다. apply, 단건 조회, search 모두 해당한다. **브랜치 env가 없으면 하네스는 실행을 거부한다.**
- 호출: `POST /api/v2/ontologies/{ontology}/actions/syn-commit/apply?branch=…`, `options: { mode: "VALIDATE_AND_EXECUTE", returnEdits: "ALL" }`. 첫 호출만은 `VALIDATE_ONLY`로 보내서, 브랜치 지정과 권한이 맞는지 먼저 확인한다.
- 요청마다 기록하는 것: HTTP status, validation 결과, 에러 이름·분류·메시지(STALE의 observed 포함), 응답 edits. JSONL로 저장하고 커밋하지 않는다.
- **중간 브랜치 조회:** 경쟁 실험에서 B의 응답을 받은 직후, A의 응답을 받기 전에 다음을 조회해서 기록한다.
  - Scope 단건
  - A의 `receiptKey`
  - 조회 시점에 A의 응답이 아직 오지 않았다는 사실
- **최종 판정 조회:** 같은 브랜치에서 Scope 단건과 `scopeKey`로 필터한 Receipt 목록을 조회한다. 응답 edits는 참고용으로만 본다.
- **호출 상한:** 하네스는 apply 호출 수를 로컬 카운터로 세고, §10의 상한을 넘으면 실행을 거부한다.

---

## 7. 실험과 증거 채택 규칙

### 순서 증거

클라이언트 시각(`sentAt`/`doneAt`)과 Receipt의 `readAt`/`emitAt`은 서버 커밋 시각이 아니다. 게다가 실패한 요청에는 Receipt가 없다. 그래서 이 값들은 **순서 증거로 쓰지 않는다.** 순서는 다음 관측으로만 증명한다.

- **"A가 B보다 먼저 읽었다":** 성공한 A의 Receipt에 `observedVersion=n`이 남았는데, B가 n+1을 커밋했다. 또는 A가 충돌 실패했다.
  - A가 `STALE(observed=n+1)`로 실패했다면, A는 B보다 *나중에* 읽은 것이다. 이 경우 경쟁이 성립하지 않았다.
- **"B의 커밋이 A의 커밋보다 먼저다":** 중간 브랜치 조회에서 B의 갱신은 보이고 A의 Receipt는 없었으며, 그 시점에 A의 응답이 아직 오지 않았다.

### 채택 규칙

- **E2, E3:** 다음 세 가지 관측으로 판정한다.
  - 충돌 오류가 실제로 났는가
  - 성공한 Receipt들의 `observedVersion`
  - 최종 상태
  
  두 APPLIED Receipt의 `observedVersion`이 같으면 **lost update(F2)가 증명된 것이다.** 순서를 증명할 수 없는 run은 **보류**하고 판정에 쓰지 않는다.
- **E5:** 위 "순서 증거" 두 가지가 모두 관측된 run만 채택한다(§7 E5 절차).
- **충돌이 관측되지 않음**은 "충돌이 없다"는 증거가 아니다.
- **강제 실패(E1):** apply 결과가 실제로 실패로 관측된 run만 원자성 근거로 쓴다. `dupReceipt`와 `updateMissingScope` 둘 다 실패를 만들지 못하면 Q1의 원자성은 **판정 보류**다.
- **멱등 성공:** 같은 요청을 재시도했을 때 세 가지를 모두 만족해야 한다. ① validation이 `VALID` ② 새 edit가 0건 ③ 재조회 결과 Receipt가 1건 그대로이고 Scope도 그대로. 재시도가 PK 중복으로 **거부되는 것은 "중복 차단"이지 멱등 성공이 아니다.**

### 실험 매트릭스

| ID | 목적 | 절차 | 판정 |
|----|-----|-----|-----|
| **E0** | Q1 기본, U1 | 새 scope에서 생성(v0→1), 갱신(v1→2), 같은 값으로 noop(v2 유지) | 세 경로 모두 validation 결과와 재조회가 일치하는지 |
| **E1** | Q1 원자성, U3 | (a) Receipt를 먼저 만든 뒤 `skipIdempotencyCheck=true`로 같은 키를 다시 생성하면서 Scope도 갱신 (b) `failMode=updateMissingScope` (c) 각각 `editOrder` 2가지 | 실패가 관측된 run에서 Scope가 그대로이고 Receipt가 없는지 |
| **E2** | ① 동시 최초 생성, U2/U4 | (a) 새 scope에 K=5 병렬, 서로 다른 requestId, `expectedVersion=0` (b) A(`delayMs=3000`) 발사 후 B 발사, 중간 조회 | 충돌 오류 수, 성공 Receipt들의 `observedVersion`, 최종 version. 둘 이상이 `observedVersion=0`으로 성공하면 F2 |
| **E3** | ② 오래된 기대버전, U4 | (a) 단순: v=3인 scope에 `expectedVersion=1` → STALE (b) 경쟁: A(delay, expected=n, 값 X→Y), 이어서 B(expected=n, 값 X→Z), 중간 조회 | (b): A가 충돌 실패하면 U4=충돌. A가 `observedVersion=n`으로 성공하면 F2. A가 `STALE(observed=n+1)`이면 경쟁 미성립으로 보류 |
| **E4** | ③ 같은 요청 재시도 | (a) 성공 후 같은 요청 재전송 (writerTag만 바꾼 경우 포함) (b) 같은 requestId로 K=5 병렬 (c) 같은 requestId 2건, 하나에 `delayMs` (d) 같은 requestId, 다른 `desiredValue` → REQUEST_ID_REUSED (e) STALE로 실패한 요청을 갱신된 expectedVersion과 **새 requestId**로 재시도 | (a)는 멱등 성공 3조건. (b)(c)는 Receipt 1건, version +1만이고, 나머지를 멱등 성공과 중복 차단으로 구분 |
| **E5** | ④ noop과 갱신의 경쟁, U5/U6, F1 | 아래 절차 | 아래 판정 |
| E6 (조건부) | 보완책 | U4가 "둘 다 성공"이고 U2가 "거부"일 때만: `SynVersionSlot`(PK=`{scopeKey}#{n}`)을 batch에 추가하고 E3b를 다시 실행 | slot PK 충돌로 CAS가 되는지 |

### E5 절차 (순서 증명 포함)

준비: Scope 값=X, version=n.

1. A를 보낸다: `desiredValue=X`(noop), `expectedVersion=n`, `delayMs=4000`.
2. 1초 뒤 B를 보낸다: `desiredValue=Y`, `expectedVersion=n`, `delayMs=0`.
3. B가 `VALID`로 끝나면 **즉시 중간 브랜치 조회**를 하고 기록한다.
   - 기대: Scope 값=Y, version=n+1. A의 Receipt는 없다. A의 응답은 아직 오지 않았다.
   - 셋 중 하나라도 다르면 그 run은 **보류**한다.
4. A의 응답을 받고 최종 조회를 한다.

| A의 결과 | 판정 |
|---------|-----|
| `VALID`, NOOP Receipt `observedVersion=n` | **F1 발생(write skew 증명).** 3단계에서 B의 갱신이 이미 보였는데, A가 그보다 옛 버전 n을 근거로 NOOP Receipt를 남겼다 |
| 충돌 실패, Receipt 없음 | F1 방지됨 |
| `STALE(observed=n+1)` | A가 B 이후에 읽은 것이다. 경쟁 미성립으로 보류 |

(a) `noopTouchScope=false`, (b) `noopTouchScope=true` 두 경우를 각각 실행한다. 문서상 기대는 (a) F1 발생, (b) F1 방지다.

---

## 8. 금지 동작과 불변식

### 금지 동작 (이 패턴이 막아야 하는 것)

| ID | 금지 동작 | 검사 방법 |
|----|---------|---------|
| **F1** | 다른 요청이 Scope 값을 바꿔 커밋한 **뒤에**, 바뀌기 **전** 값을 근거로 한 NOOP Receipt가 커밋되는 것. 즉 "이미 같은 값이라 할 일 없음"이라는 기록이 사실과 다른 상태에서 남는 것 | E5의 순서 관측(§7). 최종 상태만으로는 검사할 수 없다. noop과 갱신이 겹쳐 둘 다 성공했다는 사실만으로는 위반이 아니다 |
| **F2** | 같은 version을 근거로 한 갱신 두 건이 모두 커밋되는 것(lost update) | 성공한 APPLIED Receipt 두 건의 `observedVersion`이 같은지 |
| **F3** | 같은 요청의 재시도가 Scope를 두 번 바꾸거나 Receipt를 두 건 남기는 것 | I4 |

### 불변식 (매 run 최종 조회 후 검사)

| ID | 불변식 | 위반이 의미하는 것 |
|----|-------|---------------|
| I1 | `Scope.version == count(Receipt where scopeKey, outcome=APPLIED)` (NOOP Receipt는 세지 않는다) | lost update, 또는 고아 Scope/Receipt |
| I2 | APPLIED Receipt의 `resultVersion` 집합 = {1..version}, 중복 없음 | F2 |
| I3 | 실패한 요청의 `receiptKey`로는 Receipt가 없음 | 부분 반영 |
| I4 | `receiptKey`당 Receipt ≤ 1, 재시도로 version이 다시 오르지 않음 | F3 |

결과표 컬럼: `실험 · run · 채택/보류(사유) · 성공 수 · 실패 수(분류별) · 성공 Receipt의 observedVersion · 중간 조회 결과 · 최종 value/version · I1–I4 · F1–F3 · 설정 확인(전/후) · 누적 apply 수`

---

## 9. 결과 해석 → 설계 함의

| 관측 | 함의 |
|-----|-----|
| U1 가능 + U3 롤백(실패 관측됨) | **Q1 = 예.** Scope와 Receipt를 한 Action에서 원자적으로 저장해도 된다 |
| E1에서 실패를 만들지 못함 | Q1 원자성은 판정 보류. 다른 실패원을 찾아야 한다 |
| U4 충돌 실패 | 같은 Scope를 쓰는 요청은 플랫폼이 직렬화한다. 클라이언트는 충돌 실패를 받으면 재조회하고 **새 requestId**로 재시도한다 |
| F2 발생 | lost update. U2가 거부라면 E6 slot 패턴으로 보완하고, 아니라면 단일 작성자 직렬화가 필요하다 |
| E5(a)에서 F1 발생 | **noop이 Receipt만 쓰는 설계는 쓸 수 없다** |
| E5(b)에서 F1 방지 | noop에서도 Scope를 쓰면(touch) F1을 막을 수 있다. 대가는 noop 사이의 충돌 증가 |
| U2 거부 | 중복 생성은 막힌다. 그러나 멱등 성공은 함수의 Receipt 조회 경로(E4a)로만 증명된다 |
| 보류 run이 많음 | 판정하지 않고 §10 상한 안에서만 반복한다 |

---

## 10. 승인 단계, apply 전 점검, 호출 상한

### 승인 단계 (각각 따로 승인)

| 단계 | 내용 |
|-----|-----|
| 🔒 **G1 리소스 생성** | 합성 프로젝트, 빈 데이터셋 2개, Functions 리포 생성. Global Branch 생성, 브랜치에서 객체 타입 2개 생성 |
| 🔒 **G2 게시와 Action 생성** | 브랜치에서 Function 버전 게시(태그/릴리스), Action 타입 `syn-commit` 생성과 §3 설정 |
| 🔒 **G3 실제 apply 시작** | 아래 점검표를 모두 통과한 뒤, 1차 호출 상한 안에서 E0–E5를 1회씩 실행 |
| 🔒 **G4 추가 반복** | 보류되거나 불명확한 실험만, 추가 상한 안에서 반복 |
| 🔒 **G5 정리** | 임시 토큰 폐기. 브랜치와 합성 리소스를 보관할지 삭제할지 결정 |

임시 토큰과 브랜치 RID는 사용자가 G3 직전에 터미널 env로 넣는다. 둘 다 저장소에 커밋하지 않는다.

### apply 전 점검표 (G3 조건)

- [ ] `SynScope`, `SynReceipt`가 **해당 브랜치에서** 인덱싱 완료 상태다
- [ ] `syn-commit`이 **브랜치에 게시된 Function 버전**을 가리킨다(버전 기록)
- [ ] Action 제출 조건이 합성 테스트 사용자(또는 테스트 그룹)로 제한돼 있다
- [ ] 외부 부수효과가 없다: 함수에 외부 호출이 없고, Action에 알림·웹훅·side effect가 설정돼 있지 않다
- [ ] §3 설정 3개가 맞다(화면 기록)
- [ ] 하네스의 첫 `VALIDATE_ONLY` 호출이 지정한 브랜치에서 `VALID`다

### 호출 상한

| 구분 | apply 상한 | 내용 |
|-----|-----------|-----|
| 1차(G3) | **50회** | E0–E5를 각 1회씩. 예상 약 40회(E0 3, E1 6, E2 7, E3 7, E4 12, E5 6) |
| 추가(G4) | **50회** | 보류되거나 불명확한 실험만, 실험당 최대 2회 추가 |
| 총 상한 | **100회** | 넘으면 하네스가 거부한다. 더 필요하면 결과를 보고 다시 승인받는다 |

조회 호출은 run당 중간 조회 1회와 최종 조회 1회로 제한하고, 폴링하지 않는다.

---

## 11. 범위 밖과 한계

- 범위 밖: Main 병합과 Main 시험, `applyBatch` API, 함수 batched execution, Staged writes, Read committed 격리, Automate/웹훅, OSv1, 다중 Scope 트랜잭션.
- 결과는 **이 브랜치와 이 설정(§3)에서만** 유효하다. API 문서에는 브랜치 지원이 실험적(experimental)이라고 적혀 있다.
- 동시성 결과는 비결정적이다. §7 채택 규칙을 통과한 run만 근거로 쓰고, 보류 run이 남으면 그 항목은 판정하지 않은 채로 보고한다.
- 개발자 티어에서의 측정이 다른 enrollment나 티어에서도 같다는 보장은 없다.

## 참고 문서

- [Action types: Consistency guarantees](https://www.palantir.com/docs/foundry/action-types/consistency-guarantees/)
- [API: Apply Action](https://www.palantir.com/docs/foundry/api/ontologies-v2-resources/actions/apply-action)
