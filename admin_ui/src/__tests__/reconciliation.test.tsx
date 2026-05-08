import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, afterEach, vi, beforeEach } from "vitest";
import ReconciliationView from "../components/ReconciliationView";
import { setStoredToken, clearStoredToken } from "../api/client";
import { VALID_TOKEN } from "./test-utils/fixtures";

beforeEach(() => {
  setStoredToken(VALID_TOKEN);
});

afterEach(() => {
  vi.restoreAllMocks();
  clearStoredToken();
});

/* ───────────────────────────────────────────
 * ReconciliationView: Empty state (no API calls — client_id heuristic removed)
 * ─────────────────────────────────────────── */
describe("ReconciliationView empty state", () => {
  it("shows empty state for locks and runs when no account_id is available", async () => {
    render(<ReconciliationView />);

    await waitFor(() => {
      expect(screen.getByText("정합성 점검")).toBeInTheDocument();
    });

    // Active Locks section — empty state
    expect(screen.getByText("활성 잠금")).toBeInTheDocument();
    expect(screen.getByText("차단 잠금이 없습니다.")).toBeInTheDocument();

    // Reconciliation Runs section — empty state
    expect(screen.getByText("정합성 점검 실행")).toBeInTheDocument();
    expect(screen.getByText("정합성 점검 실행 기록이 없습니다.")).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * No warning banner when no locks
 * ─────────────────────────────────────────── */
describe("ReconciliationView no locks warning", () => {
  it("shows no warning banner when locks list is empty", async () => {
    render(<ReconciliationView />);

    await waitFor(() => {
      expect(screen.getByText("정합성 점검")).toBeInTheDocument();
    });

    // No warning banner
    expect(
      screen.queryByText(/활성 차단 잠금/i),
    ).not.toBeInTheDocument();
  });
});
