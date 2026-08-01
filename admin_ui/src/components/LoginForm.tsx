import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { API_BASE_URL, ApiResponseError, UnauthorizedError } from "../api/client";
import { ShieldAlert } from "lucide-react";

export function LoginForm() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [tokenInput, setTokenInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isVerifying, setIsVerifying] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const trimmed = tokenInput.trim();
    if (!trimmed) {
      setError("토큰이 비어 있습니다.");
      return;
    }

    setError(null);
    setIsVerifying(true);

    // Verify token by making a health check call
    try {
      const res = await fetch(`${API_BASE_URL}/orders`, {
        headers: { Authorization: `Bearer ${trimmed}` },
      });

      if (res.status === 401) {
        throw new UnauthorizedError();
      }

      if (!res.ok) {
        throw new ApiResponseError(res.status, res.statusText);
      }

      // Token is valid
      login(trimmed);
      navigate("/");
    } catch (err) {
      if (err instanceof UnauthorizedError) {
        setError("유효하지 않은 토큰입니다. 서버가 인증을 거부했습니다.");
      } else if (err instanceof ApiResponseError) {
        setError(`서버 오류: ${err.detail}`);
      } else {
        setError("서버에 연결할 수 없습니다. API가 실행 중인지 확인하세요.");
      }
    } finally {
      setIsVerifying(false);
    }
  }

  return (
    <div className="flex items-center justify-center min-h-screen bg-[#f8fafc] p-4">
      <div className="w-full max-w-md bg-white rounded-xl border border-[#e2e8f0] p-8 shadow-sm">
        {/* Logo / Header */}
        <div className="flex items-center gap-3 mb-6">
          <div className="w-10 h-10 rounded-lg bg-[#3b82f6] flex items-center justify-center text-white font-bold text-lg">
            A
          </div>
          <div>
            <h1 className="text-xl font-semibold text-[#0f172a]">운영 콘솔</h1>
            <p className="text-sm text-[#64748b]">운영 대시보드</p>
          </div>
        </div>

        <p className="text-sm text-[#64748b] mb-6 leading-relaxed">
          <code className="text-xs bg-[#f1f5f9] px-1.5 py-0.5 rounded text-[#0f172a]">INSPECTION_API_TOKEN</code>을 입력하여 대시보드에 접속하세요.
          토큰은 세션에만 저장되며 로그아웃 또는 탭 종료 시 삭제됩니다.
        </p>

        {error && (
          <div className="flex items-center gap-2 p-3 mb-4 bg-[#fef2f2] border border-[#f87171] rounded-lg">
            <ShieldAlert className="h-4 w-4 text-[#dc2626] shrink-0" />
            <span className="text-sm text-[#dc2626]">{error}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="token-input" className="block text-sm font-medium text-[#0f172a] mb-1.5">
              Bearer 토큰
            </label>
            <input
              id="token-input"
              type="password"
              placeholder="토큰을 붙여넣으세요..."
              value={tokenInput}
              onChange={(e) => setTokenInput(e.target.value)}
              autoFocus
              className="w-full px-3 py-2 text-sm border border-[#e2e8f0] rounded-lg bg-white text-[#0f172a] placeholder-[#94a3b8] focus:outline-none focus:ring-2 focus:ring-[#3b82f6] focus:border-transparent transition-shadow"
            />
          </div>

          <button
            type="submit"
            disabled={isVerifying || !tokenInput.trim()}
            className="w-full px-4 py-2.5 text-sm font-medium text-white bg-[#3b82f6] rounded-lg hover:bg-[#2563eb] disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {isVerifying ? "확인 중..." : "대시보드 접속"}
          </button>
        </form>
      </div>
    </div>
  );
}
