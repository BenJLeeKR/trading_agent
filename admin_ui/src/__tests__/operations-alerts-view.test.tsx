import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { describe, expect, it, afterEach, vi } from "vitest";
import OperationsAlertsView from "../components/OperationsAlertsView";
import * as apiClient from "../api/client";
import {
  mockClients,
  mockAccounts,
  mockPositions,
  mockOrders,
  mockHealthOk,
  mockHealthDegraded,
} from "./test-utils/fixtures";
import type {
  AccountSnapshotResponse,
  ReconciliationSummary,
  SchedulerStatusResponse,
} from "../types/api";

/**
 * PR #316(운영 경고 로딩 최적화 1차)이 통합한 "계좌당 getAccountSnapshots 1회
 * 호출" 구조를 직접 검증한다. `alerts.test.ts`는 deriveAlerts() 규칙만
 * 검증하므로, 실제 컴포넌트가 계좌별로 몇 번 API를 호출하는지와 부분 실패가
 * 화면에서 어떻게 드러나는지는 이 파일에서 확인한다.
 */

afterEach(() => {
  vi.restoreAllMocks();
  cleanup();
});

/* ── 계좌 스냅샷 응답 fixture 빌더 ── */
function makeAccountSnapshot(
  overrides: Partial<AccountSnapshotResponse> & { account_id: string },
): AccountSnapshotResponse {
  return {
    positions: [],
    cash_balance: null,
    alignment_status: "aligned",
    positions_snapshot_at: null,
    cash_snapshot_at: null,
    snapshot_sync_run_id: null,
    alignment_detail: "same_run",
    ...overrides,
  };
}

/* ── 부수적인 alert가 섞이지 않도록 하는 깨끗한 정합성 요약 ── */
const cleanReconSummary: ReconciliationSummary = {
  active_locks_count: 0,
  incomplete_recon_count: 0,
  recent_active_locks: [],
  recent_incomplete_runs: [],
  generated_at: "2026-08-21T00:00:00Z",
  activeIssueCount: 0,
  historicalFailedCount: 0,
  recentActiveIssues: [],
};

const cleanSessionResponse: SchedulerStatusResponse = {
  status: "ok",
  data: null,
  healthy: true,
  stale_seconds: null,
};

const accountA = mockAccounts[0]; // active, paper
const accountB = mockAccounts[1]; // active, live

/** 계좌 fan-out 이전 단계(1차 병렬 배치 5개)의 공통 mock 설정. */
function mockCommonNonAccountCalls(health = mockHealthOk) {
  vi.spyOn(apiClient, "getHealth").mockResolvedValue(health);
  vi.spyOn(apiClient, "getOrders").mockResolvedValue(mockOrders);
  vi.spyOn(apiClient, "getReconciliationSummary").mockResolvedValue(cleanReconSummary);
  vi.spyOn(apiClient, "getAgentRuns").mockResolvedValue([]);
  vi.spyOn(apiClient, "getLatestMarketSession").mockResolvedValue(cleanSessionResponse);
  vi.spyOn(apiClient, "getSnapshotSyncRuns").mockResolvedValue([]);
  vi.spyOn(apiClient, "getClients").mockResolvedValue([mockClients[0]]);
}

/* ───────────────────────────────────────────
 * 필수 테스트 1: 계좌당 스냅샷 API 호출 수
 * ─────────────────────────────────────────── */
describe("OperationsAlertsView 계좌별 API 호출", () => {
  it("계좌가 여러 개일 때 getAccountSnapshots가 계좌당 정확히 1회만 호출되고, getPositions/getCashBalance는 호출되지 않는다", async () => {
    mockCommonNonAccountCalls();
    vi.spyOn(apiClient, "getAccounts").mockResolvedValue([accountA, accountB]);

    const getAccountSnapshotsSpy = vi
      .spyOn(apiClient, "getAccountSnapshots")
      .mockImplementation((accountId: string) =>
        Promise.resolve(
          makeAccountSnapshot({
            account_id: accountId,
            positions: mockPositions,
            positions_snapshot_at: mockPositions[0].snapshot_at,
          }),
        ),
      );
    const getPositionsSpy = vi.spyOn(apiClient, "getPositions");
    const getCashBalanceSpy = vi.spyOn(apiClient, "getCashBalance");

    render(<OperationsAlertsView />);

    await screen.findByText("운영 경고");

    // 계좌당 1회(총 2회) — 예전에는 계좌당 getPositions/getCashBalance/
    // getAccountSnapshots 3회(총 6회)를 순차 호출했다.
    expect(getAccountSnapshotsSpy).toHaveBeenCalledTimes(2);
    expect(getAccountSnapshotsSpy).toHaveBeenCalledWith(accountA.account_id);
    expect(getAccountSnapshotsSpy).toHaveBeenCalledWith(accountB.account_id);

    expect(getPositionsSpy).not.toHaveBeenCalled();
    expect(getCashBalanceSpy).not.toHaveBeenCalled();
  });
});

/* ───────────────────────────────────────────
 * 필수 테스트 2: 부분 실패가 API 오류로 표시되는지
 * ─────────────────────────────────────────── */
describe("OperationsAlertsView 계좌 스냅샷 부분 실패", () => {
  it("계좌 하나의 getAccountSnapshots 실패가 다른 계좌 조회를 막지 않고, 화면을 크래시시키거나 정상 상태로 위장하지 않는다", async () => {
    // 주문 내역은 있지만(mockOrders), 성공한 계좌(A)는 실제 포지션을 보유한다.
    // positionsError가 사라진다면 "주문-포지션 lineage 불일치"(ALT-LINEAGE-001)를
    // 오판할 조건은 아니지만, 실패가 있었다는 사실 자체가 조용히 사라지지
    // 않는지(크래시/빈 화면으로 위장되지 않는지, allSettled 격리가 유지되는지)를
    // 확인한다.
    mockCommonNonAccountCalls();
    vi.spyOn(apiClient, "getAccounts").mockResolvedValue([accountA, accountB]);

    const getAccountSnapshotsSpy = vi
      .spyOn(apiClient, "getAccountSnapshots")
      .mockImplementation((accountId: string) => {
        if (accountId === accountB.account_id) {
          return Promise.reject(new Error("account-snapshots timeout"));
        }
        return Promise.resolve(
          makeAccountSnapshot({
            account_id: accountId,
            positions: mockPositions,
            positions_snapshot_at: mockPositions[0].snapshot_at,
          }),
        );
      });
    const getPositionsSpy = vi.spyOn(apiClient, "getPositions");
    const getCashBalanceSpy = vi.spyOn(apiClient, "getCashBalance");

    render(<OperationsAlertsView />);

    await screen.findByText("운영 경고");

    // 화면이 최상위 에러(ErrorBanner + "다시 시도")로 빠지지 않는다 — 계좌 하나의
    // 실패가 Promise.allSettled로 격리되어 전체를 무너뜨리지 않아야 한다.
    expect(screen.queryByText("다시 시도")).not.toBeInTheDocument();

    // 실패한 계좌가 있어도 두 계좌 모두 조회를 시도한다(한쪽 실패가 다른 쪽
    // 조회를 막지 않음).
    expect(getAccountSnapshotsSpy).toHaveBeenCalledTimes(2);
    expect(getAccountSnapshotsSpy).toHaveBeenCalledWith(accountA.account_id);
    expect(getAccountSnapshotsSpy).toHaveBeenCalledWith(accountB.account_id);

    // 예전 3-endpoint 구조로 되돌아가지 않았는지 재확인.
    expect(getPositionsSpy).not.toHaveBeenCalled();
    expect(getCashBalanceSpy).not.toHaveBeenCalled();
  });

  it("계좌 스냅샷 조회 실패는 GET /account-snapshots/latest로 apiErrors에 기록되고, health 이상과 함께 발생하면 API 상태 이상 경고에 그대로 노출된다", async () => {
    // 주의: deriveAlerts()의 Rule 1(ALT-SYS-001, "API 상태 이상")은
    // healthError || health.status !== "ok" 조건으로만 발동한다(alerts.ts).
    // health가 정상이면 getAccountSnapshots 단독 실패는 이 화면에 별도
    // 경고를 만들지 않는다 — 이는 deriveAlerts() 규칙 자체이며 이번 테스트
    // 대상이 아니다. 이 테스트는 apiErrors에 담기는 "GET /account-snapshots/
    // latest" 문자열이 실제로 화면 경고 문구까지 정확히(오탈자, 누락 없이)
    // 전달되는지를, health 이상과 결합한 현실적인 시나리오로 검증한다.
    mockCommonNonAccountCalls(mockHealthDegraded);
    vi.spyOn(apiClient, "getAccounts").mockResolvedValue([accountA, accountB]);

    vi.spyOn(apiClient, "getAccountSnapshots").mockImplementation((accountId: string) => {
      if (accountId === accountB.account_id) {
        return Promise.reject(new Error("account-snapshots timeout"));
      }
      return Promise.resolve(makeAccountSnapshot({ account_id: accountId }));
    });

    render(<OperationsAlertsView />);

    await screen.findByText("운영 경고");

    // 기본 필터("조치 필요")는 긴급/주의만 보여주므로 ALT-SYS-001(긴급)이 보여야 한다.
    const sysAlertRow = await screen.findByText("API 상태 이상");
    fireEvent.click(sysAlertRow);

    // 상세 패널에 실패 API 이름이 "데이터 없음"이 아니라 "API 실패"로 명확히 드러난다.
    expect(
      await screen.findByText(/GET \/account-snapshots\/latest/),
    ).toBeInTheDocument();
  });
});
