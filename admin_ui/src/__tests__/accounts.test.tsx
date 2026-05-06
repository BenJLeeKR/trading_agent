import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, afterEach, vi, beforeEach } from "vitest";
import AccountsView from "../components/AccountsView";
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
 * AccountsView: Empty state (no API calls — client_id heuristic removed)
 * ─────────────────────────────────────────── */
describe("AccountsView empty state", () => {
  it("shows empty state when no client_id is available", async () => {
    render(<AccountsView />);

    await waitFor(() => {
      expect(screen.getByText("Accounts")).toBeInTheDocument();
    });

    // No accounts data — empty message
    expect(screen.getByText("No accounts found.")).toBeInTheDocument();
  });
});
