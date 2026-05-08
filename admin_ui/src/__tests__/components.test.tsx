import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { DataTable } from "../components/common/DataTable";
import type { Column } from "../components/common/DataTable";
import { StatusBadge } from "../components/common/StatusBadge";
import { ErrorBanner } from "../components/common/ErrorBanner";
import { LoadingSpinner } from "../components/common/LoadingSpinner";

/* ───────────────────────────────────────────
 * DataTable
 * ─────────────────────────────────────────── */
interface TestRow {
  id: string;
  name: string;
  value: number;
}

const testColumns: Column<TestRow>[] = [
  { key: "name", header: "이름" },
  { key: "value", header: "값" },
];

const testData: TestRow[] = [
  { id: "1", name: "Alpha", value: 100 },
  { id: "2", name: "Beta", value: 200 },
];

describe("DataTable", () => {
  /* Scenario 1: 렌더링 */
  it("renders column headers and data rows", () => {
    render(
      <DataTable
        columns={testColumns}
        data={testData}
        idKey="id"
      />,
    );

    expect(screen.getByText("이름")).toBeInTheDocument();
    expect(screen.getByText("값")).toBeInTheDocument();
    expect(screen.getByText("Alpha")).toBeInTheDocument();
    expect(screen.getByText("Beta")).toBeInTheDocument();
    expect(screen.getByText("100")).toBeInTheDocument();
    expect(screen.getByText("200")).toBeInTheDocument();
  });

  /* Scenario 2: 빈 상태 */
  it("shows emptyMessage when data is empty", () => {
    render(
      <DataTable
        columns={testColumns}
        data={[]}
        idKey="id"
        emptyMessage="항목이 없습니다."
      />,
    );

    expect(screen.getByText("항목이 없습니다.")).toBeInTheDocument();
  });

  /* Scenario 3: 로딩 상태 */
  it("shows loading spinner when isLoading is true", () => {
    render(
      <DataTable
        columns={testColumns}
        data={[]}
        idKey="id"
        isLoading
      />,
    );

    expect(screen.getByText("로딩 중...")).toBeInTheDocument();
  });

  /* Scenario 4: Row click */
  it("calls onRowClick when a row is clicked", async () => {
    const user = userEvent.setup();
    const onRowClick = vi.fn();

    render(
      <DataTable
        columns={testColumns}
        data={testData}
        idKey="id"
        onRowClick={onRowClick}
      />,
    );

    await user.click(screen.getByText("Alpha"));
    expect(onRowClick).toHaveBeenCalledTimes(1);
    expect(onRowClick).toHaveBeenCalledWith(
      expect.objectContaining({ id: "1", name: "Alpha" }),
    );
  });
});

/* ───────────────────────────────────────────
 * StatusBadge
 * ─────────────────────────────────────────── */
describe("StatusBadge", () => {
  /* Scenario 5: variant별 렌더링 */
  it("renders status text", () => {
    const { rerender } = render(<StatusBadge status="filled" />);
    expect(screen.getByText("filled")).toBeInTheDocument();

    rerender(<StatusBadge status="pending" />);
    expect(screen.getByText("pending")).toBeInTheDocument();

    rerender(<StatusBadge status="rejected" />);
    expect(screen.getByText("rejected")).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * ErrorBanner
 * ─────────────────────────────────────────── */
describe("ErrorBanner", () => {
  /* Scenario 6: 렌더링 및 닫기 */
  it("renders message and calls onDismiss on click", async () => {
    const user = userEvent.setup();
    const onDismiss = vi.fn();

    render(
      <ErrorBanner message="Something went wrong." onDismiss={onDismiss} />,
    );

    expect(screen.getByText(/Something went wrong/)).toBeInTheDocument();

    // Click dismiss button
    await user.click(screen.getByRole("button"));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });
});

/* ───────────────────────────────────────────
 * LoadingSpinner
 * ─────────────────────────────────────────── */
describe("LoadingSpinner", () => {
  /* Scenario 7: 렌더링 */
  it("renders loading text", () => {
    render(<LoadingSpinner />);
    expect(screen.getByText("로딩 중...")).toBeInTheDocument();
  });

  it("renders custom text", () => {
    render(<LoadingSpinner text="데이터를 불러오는 중..." />);
    expect(screen.getByText("데이터를 불러오는 중...")).toBeInTheDocument();
  });
});
