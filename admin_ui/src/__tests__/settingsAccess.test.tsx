import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, afterEach, vi } from "vitest";
import SettingsAccessView from "../components/SettingsAccessView";
import { AuthProvider } from "../context/AuthContext";
import { setStoredToken, clearStoredToken } from "../api/client";
import { mockFetchOnce, mockFetchError, mockFetchNetworkError } from "./test-utils/mockFetch";
import { VALID_TOKEN } from "./test-utils/fixtures";

/**
 * `설정 > 권한 확인`(`/settings/access`) — role 상태별로 화면이 명확히
 * 갈리는지 확인한다. viewer/admin이 정확히 구분되는지, 조회 실패가
 * admin으로 대체되지 않는지가 이 파일의 핵심 검증 대상이다.
 */

afterEach(() => {
  vi.restoreAllMocks();
  clearStoredToken();
});

function renderView() {
  setStoredToken(VALID_TOKEN);
  return render(
    <MemoryRouter>
      <AuthProvider>
        <SettingsAccessView />
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe("SettingsAccessView — 로딩 상태", () => {
  it("role 조회 중에는 '권한 확인 중...'을 보여준다", async () => {
    const fetchSpy = mockFetchOnce({ role: "viewer", auth_enabled: true });

    renderView();

    expect(screen.getByText("권한 확인 중...")).toBeInTheDocument();

    // 이 테스트가 끝난 뒤에도 조회가 이어지며 act() 경고를 남기지 않도록,
    // 조회가 끝날 때까지 기다린다.
    await waitFor(() => expect(fetchSpy).toHaveBeenCalled());
    await waitFor(() => {
      expect(screen.getByText("viewer")).toBeInTheDocument();
    });
  });
});

describe("SettingsAccessView — viewer/admin 표시가 정확히 갈린다", () => {
  it("viewer role이면 'viewer' 배지와 조회 전용 안내가 보인다", async () => {
    mockFetchOnce({ role: "viewer", auth_enabled: true });

    renderView();

    await waitFor(() => {
      expect(screen.getByText("viewer")).toBeInTheDocument();
    });
    expect(
      screen.getByText(/조회는 가능하지만, 설정 발행 및 운영 조치는 관리자\(admin\) 권한이 필요합니다/),
    ).toBeInTheDocument();
    // admin 전용 안내는 나타나지 않아야 한다.
    expect(screen.queryByText("설정 발행 및 운영 조치가 가능합니다.")).not.toBeInTheDocument();
  });

  it("admin role이면 'admin' 배지와 발행/조치 가능 안내가 보인다", async () => {
    mockFetchOnce({ role: "admin", auth_enabled: true });

    renderView();

    await waitFor(() => {
      expect(screen.getByText("admin")).toBeInTheDocument();
    });
    expect(screen.getByText("설정 발행 및 운영 조치가 가능합니다.")).toBeInTheDocument();
    // viewer 전용 안내는 나타나지 않아야 한다.
    expect(
      screen.queryByText(/조회는 가능하지만, 설정 발행 및 운영 조치는 관리자\(admin\) 권한이 필요합니다/),
    ).not.toBeInTheDocument();
  });

  it("확인 시각과 인증 강제 여부를 함께 보여준다", async () => {
    mockFetchOnce({ role: "admin", auth_enabled: true });

    renderView();

    await waitFor(() => {
      expect(screen.getByText("admin")).toBeInTheDocument();
    });
    expect(screen.getByText("인증 강제 여부")).toBeInTheDocument();
    expect(screen.getByText("예")).toBeInTheDocument();
    expect(screen.getByText("확인 시각(KST)")).toBeInTheDocument();
  });
});

describe("SettingsAccessView — role 조회 실패는 admin으로 대체되지 않는다", () => {
  it("403이면 '권한 없음' 안내를 보여주고 viewer/admin 어느 배지도 없다", async () => {
    mockFetchError(403, "Insufficient permissions — viewer role required");

    renderView();

    await waitFor(() => {
      expect(
        screen.getByText(/이 토큰은 최소 조회 권한\(viewer\)도 없습니다/),
      ).toBeInTheDocument();
    });
    expect(screen.queryByText("viewer")).not.toBeInTheDocument();
    expect(screen.queryByText("admin")).not.toBeInTheDocument();
  });

  it("네트워크 오류면 조회 실패 안내를 보여주고 admin으로 가정하지 않는다", async () => {
    mockFetchNetworkError();

    renderView();

    await waitFor(() => {
      expect(
        screen.getByText(/값을 admin처럼 가정하지 않습니다/),
      ).toBeInTheDocument();
    });
    expect(screen.queryByText("viewer")).not.toBeInTheDocument();
    expect(screen.queryByText("admin")).not.toBeInTheDocument();
  });

  it("'다시 확인' 버튼을 누르면 role을 다시 조회한다", async () => {
    const user = userEvent.setup();
    mockFetchNetworkError(); // 최초 조회 실패

    renderView();

    await waitFor(() => {
      expect(screen.getByText("다시 확인")).toBeInTheDocument();
    });

    mockFetchOnce({ role: "viewer", auth_enabled: true }); // 재시도는 성공
    await user.click(screen.getByText("다시 확인"));

    await waitFor(() => {
      expect(screen.getByText("viewer")).toBeInTheDocument();
    });
  });
});
