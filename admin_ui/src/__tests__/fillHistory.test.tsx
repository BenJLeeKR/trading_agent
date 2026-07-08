import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";

import FillHistoryView from "../components/FillHistoryView";
import { clearStoredToken, setStoredToken } from "../api/client";
import { VALID_TOKEN } from "./test-utils/fixtures";

/** Renders the current URL's path+search so tests can assert on navigation. */
function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location-probe">{location.pathname + location.search}</div>;
}

const fillHistoryFixture = [{
  broker_fill_snapshot_id: "fill-1",
  fill_sync_run_id: "run-1",
  account_id: "acc-1",
  account_alias: "테스트 계좌",
  account_code: "TEST-001",
  broker_name: "koreainvestment",
  broker_native_order_id: "0001234567",
  broker_fill_id: "CCLD-1",
  symbol: "005930",
  instrument_name: "삼성전자",
  side: "buy",
  order_date: "2026-06-02",
  order_status_code: "22",
  cancel_yn: "N",
  ordered_quantity: 10,
  filled_quantity: 10,
  fill_price: 71200,
  order_time: "091500",
  fill_time: "091501",
  fill_timestamp: "2026-06-02T00:15:01Z",
  created_at: "2026-06-02T00:15:02Z",
  updated_at: "2026-06-02T00:15:02Z",
}];

const fillSyncSummaryFixture = {
  last_run_started_at: "2026-06-02T00:20:00Z",
  last_run_completed_at: "2026-06-02T00:20:05Z",
  last_status: "completed",
  last_successful_run_at: "2026-06-02T00:20:00Z",
  consecutive_failures: 0,
  is_stale: false,
  stale_threshold_seconds: 1800,
};

const fillSyncRunsFixture = [{
  fill_sync_run_id: "run-1",
  trigger_type: "scheduler",
  scope: "all",
  dry_run: false,
  total_accounts: 1,
  succeeded_accounts: 1,
  partial_accounts: 0,
  failed_accounts: 0,
  skipped_accounts: 0,
  fills_synced_total: 1,
  fills_skipped_total: 0,
  error_count: 0,
  status: "completed",
  started_at: "2026-06-02T00:20:00Z",
  completed_at: "2026-06-02T00:20:05Z",
  env_filter: "paper",
  summary_json: {},
}];

beforeEach(() => {
  setStoredToken(VALID_TOKEN);
});

afterEach(() => {
  vi.restoreAllMocks();
  clearStoredToken();
});

function renderView() {
  return render(
    <MemoryRouter initialEntries={["/fills"]}>
      <Routes>
        <Route path="/fills" element={<FillHistoryView />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("FillHistoryView", () => {
  it("renders fill history table and sync cards", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => [{
          broker_fill_snapshot_id: "fill-1",
          fill_sync_run_id: "run-1",
          account_id: "acc-1",
          account_alias: "테스트 계좌",
          account_code: "TEST-001",
          broker_name: "koreainvestment",
          broker_native_order_id: "0001234567",
          broker_fill_id: "CCLD-1",
          symbol: "005930",
          instrument_name: "삼성전자",
          side: "buy",
          order_date: "2026-06-02",
          order_status_code: "22",
          cancel_yn: "N",
          ordered_quantity: 10,
          filled_quantity: 10,
          fill_price: 71200,
          order_time: "091500",
          fill_time: "091501",
          fill_timestamp: "2026-06-02T00:15:01Z",
          created_at: "2026-06-02T00:15:02Z",
          updated_at: "2026-06-02T00:15:02Z",
        }],
      } as Response)
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({
          last_run_started_at: "2026-06-02T00:20:00Z",
          last_run_completed_at: "2026-06-02T00:20:05Z",
          last_status: "completed",
          last_successful_run_at: "2026-06-02T00:20:00Z",
          consecutive_failures: 0,
          is_stale: false,
          stale_threshold_seconds: 1800,
        }),
      } as Response)
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => [{
          fill_sync_run_id: "run-1",
          trigger_type: "scheduler",
          scope: "all",
          dry_run: false,
          total_accounts: 1,
          succeeded_accounts: 1,
          partial_accounts: 0,
          failed_accounts: 0,
          skipped_accounts: 0,
          fills_synced_total: 1,
          fills_skipped_total: 0,
          error_count: 0,
          status: "completed",
          started_at: "2026-06-02T00:20:00Z",
          completed_at: "2026-06-02T00:20:05Z",
          env_filter: "paper",
          summary_json: {},
        }],
      } as Response);

    renderView();

    await waitFor(() => {
      expect(screen.getByText("체결내역")).toBeInTheDocument();
    });

    expect(screen.getByText("VTTC0081R 기반 체결 스냅샷 조회")).toBeInTheDocument();
    expect(screen.getByText("005930")).toBeInTheDocument();
    expect(screen.getByText("삼성전자")).toBeInTheDocument();
    expect(screen.getByText("0001234567")).toBeInTheDocument();
    expect(screen.getByText("테스트 계좌")).toBeInTheDocument();
    expect(screen.getByText("712,000")).toBeInTheDocument();
  });

  it("navigates to the realtime quote screen with ?symbol= when a symbol is clicked", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => fillHistoryFixture } as Response)
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => fillSyncSummaryFixture } as Response)
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => fillSyncRunsFixture } as Response);

    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/fills"]}>
        <Routes>
          <Route path="/fills" element={<FillHistoryView />} />
        </Routes>
        <LocationProbe />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("005930")).toBeInTheDocument();
    });

    await user.click(screen.getByText("005930"));

    expect(screen.getByTestId("location-probe").textContent).toBe(
      "/operations/realtime-quotes?symbol=005930",
    );
  });
});
