# Agent Inventory And Status Map

이 디렉토리는 `ENTERPRISE_TRADING_SYSTEM_DESIGN.md`의 14개 필수 Agent를
현재 코드 상태와 상세 설계 문서 기준으로 다시 정리한 자료를 담는다.

중요한 해석 원칙:

- 여기서 `Agent`는 우선 **책임 단위**다.
- 모든 Agent가 반드시 별도 LLM 런타임이나 provider 호출 단위일 필요는 없다.
- 일부는 실제 Provider AI Agent로 구현하는 것이 맞고,
  일부는 deterministic service / worker / validator / analytics job으로 구현하는 것이 맞다.
- live-safe 원칙상 broker submit, hard guardrail, reconciliation authoritative path는
  AI Agent가 직접 소유하지 않는다.

## 문서 구성

1. [01_agent_inventory_and_status.md](./01_agent_inventory_and_status.md)
   - 14개 Agent의 현재 상태, 최종 구현 형태, 코드/문서 앵커를 한 표로 정리
2. [02_agent_target_shapes.md](./02_agent_target_shapes.md)
   - 각 Agent의 최종 개발 모양, 경계, 입력/출력, 구현 원칙을 서술형으로 설명

## 현재 결론 요약

- 현재 실구현된 v1 Provider AI Agent는 3개다.
  - Event Interpretation Agent
  - AI Risk Agent
  - Final Decision Composer
- Data Collector / Execution / Data Quality 일부 책임은 이미 deterministic path로 상당 부분 구현되어 있다.
- 나머지 Agent는 장기적으로 필요하지만, 모두를 동일한 "LLM agent"로 만들 계획은 아니다.

