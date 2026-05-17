import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { DataTable } from "../components/common/DataTable";
import type { Column } from "../components/common/DataTable";
import { useState } from "react";
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
 * DataTable — Pagination
 * ─────────────────────────────────────────── */

/** Helper component that wraps DataTable with local pagination state */
function PaginatedDataTable({
  data,
  pageSize: initialPageSize = 20,
}: {
  data: TestRow[];
  pageSize?: number;
}) {
  const [page, setPage] = useState(1);
  const [size, setSize] = useState(initialPageSize);
  const totalItems = data.length;
  const totalPages = Math.max(1, Math.ceil(totalItems / size));
  const safePage = Math.min(page, totalPages);
  const paged = data.slice((safePage - 1) * size, safePage * size);

  return (
    <DataTable
      columns={testColumns}
      data={paged}
      idKey="id"
      currentPage={safePage}
      pageSize={size}
      totalItems={totalItems}
      onPageChange={setPage}
      onPageSizeChange={(newSize) => { setSize(newSize); setPage(1); }}
      pageSizeOptions={[10, 20, 50]}
    />
  );
}

const paginationTestData: TestRow[] = Array.from({ length: 42 }, (_, i) => ({
  id: String(i + 1),
  name: `Item ${i + 1}`,
  value: (i + 1) * 10,
}));

describe("DataTable pagination", () => {
  /* Scenario 8: Pagination footer 렌더링 */
  it("renders pagination footer when pagination props are provided", () => {
    render(
      <DataTable
        columns={testColumns}
        data={testData}
        idKey="id"
        currentPage={1}
        pageSize={20}
        totalItems={42}
        onPageChange={vi.fn()}
      />,
    );

    expect(screen.getByText("총 42건")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous page" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next page" })).toBeInTheDocument();
  });

  /* Scenario 9: page-size selector에 10/20/50 옵션만 있음 (5 없음) */
  it("shows page-size options 10, 20, 50 only (no 5)", () => {
    render(
      <DataTable
        columns={testColumns}
        data={testData}
        idKey="id"
        currentPage={1}
        pageSize={20}
        totalItems={42}
        onPageChange={vi.fn()}
        onPageSizeChange={vi.fn()}
        pageSizeOptions={[10, 20, 50]}
      />,
    );

    const select = screen.getByRole("combobox");
    const options = Array.from(select.children).map((opt) => (opt as HTMLOptionElement).value);
    expect(options).toEqual(["10", "20", "50"]);
    expect(options).not.toContain("5");
  });

  /* Scenario 10: page-size 기본값 20 */
  it("default page size is 20", () => {
    render(
      <DataTable
        columns={testColumns}
        data={testData}
        idKey="id"
        currentPage={1}
        totalItems={42}
        onPageChange={vi.fn()}
        onPageSizeChange={vi.fn()}
      />,
    );

    const select = screen.getByRole("combobox");
    expect((select as HTMLSelectElement).value).toBe("20");
  });

  /* Scenario 11: 현재 page 행만 렌더 */
  it("renders only rows for current page when data exceeds pageSize", () => {
    render(
      <DataTable
        columns={testColumns}
        data={paginationTestData.slice(0, 20)}
        idKey="id"
        currentPage={1}
        pageSize={20}
        totalItems={42}
        onPageChange={vi.fn()}
      />,
    );

    // First 20 items visible
    expect(screen.getByText("Item 1")).toBeInTheDocument();
    expect(screen.getByText("Item 20")).toBeInTheDocument();
    expect(screen.queryByText("Item 21")).not.toBeInTheDocument();
  });

  /* Scenario 12: Prev button disabled on first page */
  it("disables prev button on first page", () => {
    render(
      <DataTable
        columns={testColumns}
        data={testData}
        idKey="id"
        currentPage={1}
        pageSize={20}
        totalItems={42}
        onPageChange={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Previous page" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Next page" })).not.toBeDisabled();
  });

  /* Scenario 13: Next button disabled on last page */
  it("disables next button on last page", () => {
    render(
      <DataTable
        columns={testColumns}
        data={testData}
        idKey="id"
        currentPage={3}
        pageSize={20}
        totalItems={42}
        onPageChange={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled();
  });

  /* Scenario 14: Page navigation click */
  it("calls onPageChange when page button is clicked", async () => {
    const user = userEvent.setup();
    const onPageChange = vi.fn();

    render(
      <DataTable
        columns={testColumns}
        data={testData}
        idKey="id"
        currentPage={1}
        pageSize={20}
        totalItems={42}
        onPageChange={onPageChange}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Next page" }));
    expect(onPageChange).toHaveBeenCalledWith(2);
  });

  /* Scenario 15: Page size 변경 호출 */
  it("calls onPageSizeChange when page size selector changes", async () => {
    const user = userEvent.setup();
    const onPageSizeChange = vi.fn();

    render(
      <DataTable
        columns={testColumns}
        data={testData}
        idKey="id"
        currentPage={1}
        pageSize={20}
        totalItems={42}
        onPageChange={vi.fn()}
        onPageSizeChange={onPageSizeChange}
        pageSizeOptions={[10, 20, 50]}
      />,
    );

    const select = screen.getByRole("combobox");
    await user.selectOptions(select, "50");
    expect(onPageSizeChange).toHaveBeenCalledWith(50);
  });

  /* Scenario 16: 페이지 번호 버튼 렌더링 (1페이지일 때 1 2 3 ... 3) */
  it("renders correct page number buttons on page 1 with 42 items / 20 per page", () => {
    render(
      <DataTable
        columns={testColumns}
        data={testData}
        idKey="id"
        currentPage={1}
        pageSize={20}
        totalItems={42}
        onPageChange={vi.fn()}
      />,
    );

    // totalPages = ceil(42/20) = 3 → pages: 1, 2, 3
    expect(screen.getByText("1")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  /* Scenario 17: Pagination 미제공 시 footer 미표시 */
  it("does not render pagination footer when pagination props are not provided", () => {
    render(
      <DataTable
        columns={testColumns}
        data={testData}
        idKey="id"
      />,
    );

    expect(screen.queryByText("총 42건")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Previous page" })).not.toBeInTheDocument();
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
