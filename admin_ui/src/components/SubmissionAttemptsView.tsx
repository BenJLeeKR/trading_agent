import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import type { SubmissionAttemptView } from '../types/api';
import { getSubmissionAttempts } from '../api/client';
import type { Column } from './common/DataTable';
import { DataTable } from './common/DataTable';
import { StatusBadge } from './common/StatusBadge';
import { LoadingSpinner } from './common/LoadingSpinner';
import { ErrorBanner } from './common/ErrorBanner';
import { Panel } from './common/Panel';

function outcomeVariant(outcome: string | null): "success" | "error" | "warning" | "neutral" {
  switch (outcome) {
    case "accepted": return "success";
    case "rejected": return "error";
    case "exception": return "warning";
    default: return "neutral";
  }
}

function outcomeLabel(outcome: string | null): string {
  switch (outcome) {
    case "accepted": return "승인";
    case "rejected": return "거부";
    case "exception": return "예외";
    default: return "없음";
  }
}

export default function SubmissionAttemptsView() {
  const { orderId } = useParams<{ orderId: string }>();
  const [attempts, setAttempts] = useState<SubmissionAttemptView[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!orderId) return;
    setLoading(true);
    getSubmissionAttempts(orderId)
      .then(data => {
        setAttempts(data);
        setLoading(false);
      })
      .catch(err => {
        setError(err.message);
        setLoading(false);
      });
  }, [orderId]);

  if (loading) return <LoadingSpinner />;
  if (error) return <ErrorBanner message={error} />;

  const columns: Column<SubmissionAttemptView>[] = [
    {
      key: 'attempt_number',
      header: '시도',
      render: (row) => `#${row.attempt_number}`,
    },
    {
      key: 'attempt_outcome',
      header: '결과',
      render: (row) => (
        <StatusBadge variant={outcomeVariant(row.attempt_outcome)}>
          {outcomeLabel(row.attempt_outcome)}
        </StatusBadge>
      ),
    },
    {
      key: 'submitted_at',
      header: '제출 시각',
      render: (row) => {
        const d = new Date(row.submitted_at);
        return d.toLocaleString('ko-KR', { timeZone: 'Asia/Seoul' });
      },
    },
    {
      key: 'broker_name',
      header: 'Broker',
      render: (row) => row.broker_name ?? '-',
    },
    {
      key: 'broker_native_order_id',
      header: 'Native ID',
      render: (row) => row.broker_native_order_id ?? '-',
    },
    {
      key: 'broker_status',
      header: '상태',
      render: (row) => row.broker_status ?? '-',
    },
    {
      key: 'raw_code',
      header: '응답 코드',
      render: (row) => row.raw_code ?? '-',
    },
    {
      key: 'raw_message',
      header: '응답 메시지',
      render: (row) => row.raw_message ?? '-',
    },
    {
      key: 'error_type',
      header: '에러 유형',
      render: (row) => row.error_type ?? '-',
    },
    {
      key: 'http_status',
      header: 'HTTP',
      render: (row) => row.http_status?.toString() ?? '-',
    },
    {
      key: 'duration_ms',
      header: '소요 시간',
      render: (row) => row.duration_ms != null ? `${row.duration_ms}ms` : '-',
    },
  ];

  return (
    <div className="p-6">
      <div className="mb-4">
        <Link
          to={`/orders/${orderId}`}
          className="text-sm text-[#3b82f6] hover:text-[#2563eb] font-medium"
        >
          ← 주문 상세로 돌아가기
        </Link>
      </div>

      <h2 className="text-lg font-semibold text-[#0f172a] mb-4">
        제출 시도 전체 이력
      </h2>

      {attempts.length === 0 ? (
        <p className="text-sm text-[#64748b]">제출 시도 내역이 없습니다.</p>
      ) : (
        <Panel noPadding>
          <DataTable
            columns={columns}
            data={attempts}
            idKey="order_submission_attempt_id"
          />
        </Panel>
      )}
    </div>
  );
}
