import { useAuth } from "../context/AuthContext";
import { Panel } from "./common/Panel";
import { DetailField } from "./common/DetailField";
import { StatusBadge } from "./common/StatusBadge";
import { LoadingSpinner } from "./common/LoadingSpinner";
import { formatKstDateTime } from "../lib/utils";
import { ShieldCheck, Eye } from "lucide-react";

/**
 * 설정 > 권한 확인 (`/settings/access`).
 *
 * 이 화면은 "사용자 계정 관리"가 아니다 — 이 배포는 프로세스 시작 시 설정된
 * 토큰 1개와 고정 role(viewer/admin) 1개로 동작한다(`GET /auth/me` 참고,
 * `docs/08_frontend_design/2026-08-24_admin_settings_navigation_design.md`
 * §7.1 레이아웃 초안). 앞으로 추가될 설정 발행/운영 조치 버튼들은 이 화면이
 * 알려주는 role을 근거로 노출 여부를 판단한다.
 */
export default function SettingsAccessView() {
  const { role, roleStatus, authEnabled, roleCheckedAt, refreshRole } = useAuth();

  const checkedAtLabel = roleCheckedAt ? formatKstDateTime(roleCheckedAt) : "—";

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-[#0f172a]">권한 확인</h1>
        <p className="text-sm text-[#64748b] mt-1">
          현재 접속 토큰의 권한을 확인합니다. 사용자별 계정 관리 화면이 아닙니다 —
          이 배포는 토큰 1개와 고정 role 1개로 동작합니다.
        </p>
      </div>

      <Panel title="현재 접속 토큰 권한">
        {roleStatus === "idle" && (
          <p className="text-sm text-[#64748b]">로그인이 필요합니다.</p>
        )}

        {roleStatus === "loading" && <LoadingSpinner text="권한 확인 중..." />}

        {roleStatus === "unauthorized" && (
          <p className="text-sm text-[#991b1b]">
            인증이 만료되어 권한을 확인할 수 없습니다. 다시 로그인해주세요.
          </p>
        )}

        {(roleStatus === "forbidden" || roleStatus === "error") && (
          <div className="space-y-3">
            <p className="text-sm text-[#991b1b]">
              {roleStatus === "forbidden"
                ? "이 토큰은 최소 조회 권한(viewer)도 없습니다 — 배포 설정을 확인해주세요."
                : "권한을 확인하지 못했습니다(서버 오류 또는 네트워크 문제). 값을 admin처럼 가정하지 않습니다."}
            </p>
            <button
              type="button"
              onClick={() => {
                void refreshRole();
              }}
              className="text-xs font-medium text-[#3b82f6] hover:text-[#2563eb]"
            >
              다시 확인
            </button>
          </div>
        )}

        {roleStatus === "ready" && role && (
          <div className="space-y-4">
            <div className="flex items-center gap-2">
              {role === "admin" ? (
                <StatusBadge variant="success">
                  <ShieldCheck className="h-3 w-3 mr-1 inline" />
                  admin
                </StatusBadge>
              ) : (
                <StatusBadge variant="neutral">
                  <Eye className="h-3 w-3 mr-1 inline" />
                  viewer
                </StatusBadge>
              )}
            </div>

            <p className="text-sm text-[#475569]">
              {role === "admin"
                ? "설정 발행 및 운영 조치가 가능합니다."
                : "조회는 가능하지만, 설정 발행 및 운영 조치는 관리자(admin) 권한이 필요합니다."}
            </p>

            <div className="border-t border-[#e2e8f0] pt-3">
              <DetailField label="인증 강제 여부" value={authEnabled ? "예" : "아니오"} />
              <DetailField label="확인 시각(KST)" value={checkedAtLabel} mono />
            </div>

            <button
              type="button"
              onClick={() => {
                void refreshRole();
              }}
              className="text-xs font-medium text-[#3b82f6] hover:text-[#2563eb]"
            >
              다시 확인
            </button>
          </div>
        )}
      </Panel>
    </div>
  );
}
