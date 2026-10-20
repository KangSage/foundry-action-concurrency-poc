# foundry-action-concurrency-poc

Palantir Foundry의 **TS v2 Function-backed Action**에서 두 가지를 확인하는 최소 합성 PoC다.

1. 고정 PK의 `Scope` 객체와 요청별 `Receipt` 객체를 **한 edit batch**로 원자적으로 저장할 수 있는가
2. 같은 Scope에 대해 **동시 최초 생성 / 오래된 기대버전 / 같은 요청 재시도**를 하면 충돌·원자성·멱등성이 실제로 어떻게 나타나는가

상태: **설계만 있음(미실행).** 설계는 [docs/design.md](docs/design.md)에 있다.

## 구성 (예정)

| 경로 | 내용 |
|------|-----|
| `docs/design.md` | 질문, 미지수(U1–U5), 객체 모델, Action/Function 설계, 실험(E0–E6), 불변식, 결과 해석 |
| `docs/ai-harness.md` | AI 코딩 도우미 규칙: slop, merge, 설계 잠금, 모름 먼저 (PLAN 12~15) |
| `scripts/check-public-safe.sh` | 커밋 전에 비공개 정보가 섞이지 않았는지 검사 |
| `functions/` | (예정) TS v2 함수 소스 |
| `harness/` | (예정) Node 20 동시성 하네스 |
| `results/` | (예정) 익명화된 결과표. 원시 JSONL은 커밋하지 않음 |

## 공개 저장소 규칙

- 데이터와 이름은 모두 합성이다(`Syn*`). 실제 조직의 데이터, 이름, 화면은 넣지 않는다.
- Foundry 호스트명, 리소스 식별자(`ri.*`), 토큰, 계정 이메일은 커밋하지 않는다. 실행 설정은 `.env`(git 무시)로만 넣는다.
- 커밋 전에 검사 스크립트를 실행한다.

```bash
./scripts/check-public-safe.sh
```

pre-commit 훅으로 걸어 두려면 다음을 실행한다.

```bash
ln -s ../../scripts/check-public-safe.sh .git/hooks/pre-commit
```

## 라이선스

[MIT](LICENSE)
