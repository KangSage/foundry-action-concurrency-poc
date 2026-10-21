# foundry-design-notes

Palantir Foundry 설계 문서와 AI 프롬프트를 **공개로 공유**하는 저장소다.
업무 내용은 넣지 않는다. 업무에 따라 달라지는 값은 `{{빈칸}}`으로 두고, 업무를 아는 쪽(사람 또는 내부 AI)이 자기 환경에서 채운다.
설계 문서에는 코드를 넣지 않는다. 코드는 명세를 받은 쪽이 직접 작성한다.

## 구조

| 경로 | 내용 |
|------|-----|
| `AGENTS.md` | 이 저장소의 문서를 읽는 AI 규칙 (빈칸 채우기, 채운 값 커밋 금지) |
| `docs/design/` | 기능별 설계. 문서마다 끝에 "채울 것" 표 |
| `docs/poc/` | 합성 PoC 설계와 결과 |
| `docs/harness/` | AI 코딩 도우미 규칙 (설계 잠금, 모름 먼저) |
| `prompts/` | 내부 AI에 그대로 붙여 넣는 프롬프트 |
| `scripts/check-public-safe.sh` | 커밋 전 비공개 정보 검사 |

## 설계 문서

- [ingest-filter](docs/design/ingest-filter.md): 외부 데이터 복사 → 필터 → 내부 마스터
- [source-revision](docs/design/source-revision.md): 원천 행별 리비전 (REVISION · HEAD · RECEIPT), 내부 리비전과 격리
  - [source-revision-impl](docs/design/source-revision-impl.md): 구현 명세 (판정표 · 테스트 시나리오)
- [multi-source](docs/design/multi-source.md): 모든 외부 원천에 같은 틀 (설정 목록, ROW/WHOLE 모드). 시작: [원천 점검표 프롬프트](prompts/source-inventory.md)

## PoC

- [action-concurrency](docs/poc/action-concurrency/design.md): TS v2 Function-backed Action의 원자성·동시성 합성 PoC (설계만, 미실행)

## 공개 저장소 규칙

- 업무 용어, 조직·사람 이름, 실제 컬럼명, 숫자는 넣지 않는다. 중립 이름과 `{{빈칸}}`을 쓴다.
- 데이터와 이름이 필요하면 합성(`Syn*`)으로 만든다.
- Foundry 호스트명, 리소스 식별자(`ri.*`), 토큰, 계정 이메일은 커밋하지 않는다. 실행 설정은 `.env`(git 무시)로만 넣는다.
- 업무 단어 차단 목록은 `.public-safe-words`(git 무시)에 한 줄에 하나씩 둔다. 목록 자체가 업무를 드러내기 때문이다.
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
