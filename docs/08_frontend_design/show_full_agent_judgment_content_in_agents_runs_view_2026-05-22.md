# AgentsRunsView 에이전트 전체 판단내용 표시

## 1. 작업 개요
- **목표**: Admin UI `AgentsRunsView`에서 에이전트의 요약(summary)이 아닌 **전체 판단내용(`structured_output_json`)을 열람**할 수 있도록 화면 수정
- **배경**: 운영상 각 에이전트가 실제로 어떤 판단을 했는지 전체 내용 확인 필요

## 2. 기존 화면 한계
- 기존 `AgentsRunsView`는 테이블 목록만 표시
- 각 row에는 `agent_type`, `status`, `created_at` 등의 메타데이터만 표시
- 에이전트의 실제 판단내용(`structured_output_json`)은 볼 수 없었음
- 우측 `AgentRunDetailPanel`에서도 요약 정보만 표시

## 3. 수정한 파일

| 파일 | 변경 내용 |
|------|----------|
| [`admin_ui/src/components/AgentRunsTable.tsx`](admin_ui/src/components/AgentRunsTable.tsx) | row expand 기능 추가 — 각 row 좌측 expand 버튼, 클릭 시 상세 패널 확장 |
| [`admin_ui/src/styles/admin-theme.css`](admin_ui/src/styles/admin-theme.css) | `.agent-run-detail-json` CSS 클래스 추가 (monospace, scrollable, pre-wrap) |

## 4. 전체 판단내용 표시 방식

### Row Expand 구조
각 row의 첫 번째 컬럼에 `▶`/`▼` 아이콘 버튼 추가 (hover 시 배경색 변경)

### 확장 패널 (4개 섹션)

| 섹션 | 내용 | 조건 |
|------|------|------|
| 1. 메타데이터 | `agent_run_id`, `decision_context_id`, `agent_type`, `status`, `started_at`, `completed_at`, `model_id`, `prompt_id`, `temperature`, `seed` (copyable 필드 복사 버튼 포함) | 항상 표시 |
| 2. 요약 (보조) | `structured_output_json.summary` 텍스트 | summary 있을 때만 |
| 3. **⭐ 전체 판단내용** | `structured_output_json` **pretty-print JSON 전체** (`JSON.stringify(so, null, 2)`) | 항상 표시 (null이면 "판단내용 없음") |
| 4. Raw Output | `raw_output_uri` 링크 | URI 있을 때만 |

### JSON 표시 스타일
- `max-height: 400px; overflow-y: auto` — 긴 JSON도 스크롤 가능
- `#f8f9fa` 배경, `Courier New` monospace, 12px, `pre-wrap`
- 복사 버튼으로 1-click 클립보드 복사

## 5. Raw Output 지원
- `raw_output_uri` 필드가 존재할 때만 Raw Output 섹션 렌더링
- URI를 truncate하여 표시하고 ExternalLink 아이콘으로 새 탭 오픈
- 현재 API 응답에 `raw_output_uri`는 있어도 실제 raw text는 별도 조회 필요

## 6. 기존 컴포넌트 보존
- `AgentRunsView.tsx` — **변경 없음** (좌측 테이블 + 우측 detail panel 레이아웃 유지)
- `AgentRunDetailPanel.tsx` — **변경 없음** (우측 패널 기존 기능 유지)
- row expand는 `Fragment` + 조건부 `<tr>`로 기존 테이블 구조에 영향 없음

## 7. 테스트 결과
- **261개 테스트 모두 통과** (16개 테스트 파일)
- `agentRuns.test.tsx` — 12개 테스트 전부 통과
- 기존 회귀(regression) 없음

## 8. 운영 검증
- `npx vite build` — production dist 빌드 성공 (435.69 KB JS, 27.83 KB CSS)
- API 서비스 재시작 시 변경사항 반영됨
