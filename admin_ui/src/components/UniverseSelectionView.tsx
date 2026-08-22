import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Panel } from "./common/Panel";
import { StatusCard } from "./common/StatusCard";
import { StatusBadge } from "./common/StatusBadge";
import { DataTable, type Column } from "./common/DataTable";
import { LoadingSpinner } from "./common/LoadingSpinner";
import { ErrorBanner } from "./common/ErrorBanner";
import { formatKstDateTime, getKstTodayString } from "../lib/utils";
import {
  getActiveIntradayFreezeSummary,
  ApiResponseError,
  UnauthorizedError,
} from "../api/client";
import type { TradingUniverseFreezeView, TradingUniversePreviewItem } from "../types/api";

/**
 * 유니버스 선정 현황 — core / market_overlay / event_overlay 선정 종목을
 * 날짜별로 보여준다.
 *
 * 성능 원칙: 이 화면은 라이브 재계산(getTradingUniversePreview),
 * coverage-summary, market-overlay-funnel 같은 진단 API를 호출하지 않는다.
 * `GET /instruments/trading-universe/freeze-summary?business_date=...` 단
 * 하나로만 렌더링되어야 한다 — orders/accounts/health/reconciliation 등
 * 다른 API는 이 화면에 추가하지 않는다.
 */

type KnownBucket = "core" | "market_overlay" | "event_overlay";
const KNOWN_BUCKETS: KnownBucket[] = ["core", "market_overlay", "event_overlay"];

const BUCKET_LABEL: Record<KnownBucket, string> = {
  core: "core",
  market_overlay: "market_overlay",
  event_overlay: "event_overlay",
};

type ErrorKind = "network" | "auth" | "forbidden";

const ERROR_MESSAGE: Record<ErrorKind, string> = {
  network: "유니버스 선정 현황을 불러오지 못했습니다(API 실패). 다시 시도해주세요.",
  auth: "인증이 만료되어 조회에 실패했습니다. 다시 로그인해주세요.",
  forbidden: "권한이 없어 조회에 실패했습니다. 관리자에게 문의해주세요.",
};

function sourceTypeCount(counts: Record<string, number>, bucket: KnownBucket): number {
  return counts[bucket] ?? 0;
}

/** 알려진 3개 bucket 외 나머지(reconciliation_overlay/held_position/manual 등)의 합. */
function otherCount(counts: Record<string, number>): number {
  return Object.entries(counts)
    .filter(([key]) => !KNOWN_BUCKETS.includes(key as KnownBucket))
    .reduce((sum, [, value]) => sum + value, 0);
}

function itemsForBucket(
  items: TradingUniversePreviewItem[],
  bucket: KnownBucket,
): TradingUniversePreviewItem[] {
  return items.filter((item) => item.source_type === bucket);
}

function otherItems(items: TradingUniversePreviewItem[]): TradingUniversePreviewItem[] {
  return items.filter((item) => !KNOWN_BUCKETS.includes(item.source_type as KnownBucket));
}

const itemColumns: Column<TradingUniversePreviewItem>[] = [
  { key: "symbol", header: "종목", width: "100px" },
  { key: "market", header: "시장", width: "80px" },
  { key: "inclusion_reason", header: "선정 이유" },
  { key: "priority", header: "우선순위", width: "90px", align: "right" },
];

/** "기타" 리스트는 원본 source_type을 프론트가 임의 해석하지 않고 그대로 보여준다. */
const otherItemColumns: Column<TradingUniversePreviewItem>[] = [
  { key: "symbol", header: "종목", width: "100px" },
  { key: "market", header: "시장", width: "80px" },
  {
    key: "source_type",
    header: "source_type",
    width: "160px",
    render: (row) => <StatusBadge variant="neutral">{row.source_type}</StatusBadge>,
  },
  { key: "inclusion_reason", header: "선정 이유" },
  { key: "priority", header: "우선순위", width: "90px", align: "right" },
];

export default function UniverseSelectionView() {
  const [searchParams, setSearchParams] = useSearchParams();
  const businessDate = searchParams.get("date") ?? getKstTodayString();

  const [loading, setLoading] = useState(true);
  const [errorKind, setErrorKind] = useState<ErrorKind | null>(null);
  // undefined = 아직 이 날짜를 조회하지 않음, null = 조회 성공했지만 freeze 없음.
  const [data, setData] = useState<TradingUniverseFreezeView | null | undefined>(undefined);

  // 같은 날짜 재조회 시 네트워크를 다시 타지 않기 위한 최소 in-memory cache.
  // 캐시를 쓰더라도 항상 응답의 frozen_at/business_date를 그대로 화면에 표시하므로,
  // 오래된 캐시가 "새로 조회한 최신 데이터"처럼 보이지 않는다.
  const cacheRef = useRef<Map<string, TradingUniverseFreezeView | null>>(new Map());
  // 날짜를 빠르게 바꿀 때 이전 요청이 늦게 도착해 최신 날짜 화면을 덮어쓰지
  // 않도록, 요청마다 세대 번호를 매기고 최신 세대의 응답만 반영한다.
  const requestGenerationRef = useRef(0);

  useEffect(() => {
    const cached = cacheRef.current.get(businessDate);
    if (cached !== undefined) {
      setData(cached);
      setErrorKind(null);
      setLoading(false);
      return;
    }

    const generation = ++requestGenerationRef.current;
    setLoading(true);
    setErrorKind(null);
    // 날짜 전환 중 이전 날짜 데이터가 남아 "최신 데이터"처럼 보이지 않도록
    // 즉시 비워둔다(데이터 영역만 loading으로 전환, 화면 shell/날짜 선택은 유지).
    setData(undefined);

    getActiveIntradayFreezeSummary(businessDate)
      .then((result) => {
        if (generation !== requestGenerationRef.current) return; // 응답이 늦게 온 이전 요청
        cacheRef.current.set(businessDate, result);
        setData(result);
      })
      .catch((err) => {
        if (generation !== requestGenerationRef.current) return;
        if (err instanceof UnauthorizedError) {
          setErrorKind("auth");
        } else if (err instanceof ApiResponseError && err.status === 403) {
          setErrorKind("forbidden");
        } else {
          setErrorKind("network");
        }
      })
      .finally(() => {
        if (generation === requestGenerationRef.current) setLoading(false);
      });
  }, [businessDate]);

  const totalCount = data?.target_count ?? 0;
  const coreCount = useMemo(
    () => (data ? sourceTypeCount(data.source_type_counts, "core") : 0),
    [data],
  );
  const marketOverlayCount = useMemo(
    () => (data ? sourceTypeCount(data.source_type_counts, "market_overlay") : 0),
    [data],
  );
  const eventOverlayCount = useMemo(
    () => (data ? sourceTypeCount(data.source_type_counts, "event_overlay") : 0),
    [data],
  );
  const otherBucketCount = useMemo(
    () => (data ? otherCount(data.source_type_counts) : 0),
    [data],
  );

  const showNoFreeze = !loading && !errorKind && data === null;
  const showData = !loading && !errorKind && data != null;

  return (
    <div className="p-6 space-y-6">
      {/* 화면 shell/날짜 선택/헤더는 데이터 로딩과 무관하게 즉시 렌더링한다. */}
      <div>
        <h1 className="text-2xl font-semibold text-[#0f172a]">유니버스 선정 현황</h1>
        <p className="text-sm text-[#64748b] mt-1">
          날짜별 core / market_overlay / event_overlay 선정 종목 조회 (decision_loop_intraday freeze 기준)
        </p>
      </div>

      <div className="flex items-center gap-3 flex-wrap">
        <label className="text-sm text-[#475569]" htmlFor="universe-selection-date">
          조회일
        </label>
        <input
          id="universe-selection-date"
          type="date"
          value={businessDate}
          onChange={(e) => {
            const next = new URLSearchParams(searchParams);
            if (e.target.value) next.set("date", e.target.value);
            else next.delete("date");
            setSearchParams(next);
          }}
          className="h-9 rounded-md border border-[#cbd5e1] px-3 text-sm"
        />
        {showData && (
          <span className="text-xs text-[#94a3b8]">
            frozen {formatKstDateTime(data.frozen_at)}
          </span>
        )}
      </div>

      {/* 데이터 영역만 loading/error/empty 상태를 구분해 표시한다. */}
      {loading && <LoadingSpinner text="유니버스 선정 현황을 불러오는 중..." />}

      {errorKind && <ErrorBanner message={ERROR_MESSAGE[errorKind]} />}

      {showNoFreeze && (
        <div className="space-y-3">
          <div className="grid grid-cols-2 xl:grid-cols-4 gap-3">
            <StatusCard title="전체 수량" value="—" status="neutral" badgeLabel="미수집" />
            <StatusCard title="core" value="—" status="neutral" badgeLabel="미수집" />
            <StatusCard title="market_overlay" value="—" status="neutral" badgeLabel="미수집" />
            <StatusCard title="event_overlay" value="—" status="neutral" badgeLabel="미수집" />
          </div>
          <p className="text-sm text-[#64748b]">
            해당 날짜에는 freeze 결과가 없습니다(0건이 아니라 아직 수집되지 않은 상태입니다).
          </p>
        </div>
      )}

      {showData && (
        <div className="space-y-6">
          <div className="grid grid-cols-2 xl:grid-cols-4 gap-3">
            <StatusCard
              title="전체 수량"
              value={`${totalCount}건`}
              status="healthy"
              subtitle="core+market+event 합계와 다를 수 있음(기타 포함)"
            />
            <StatusCard title="core" value={`${coreCount}건`} status="healthy" />
            <StatusCard title="market_overlay" value={`${marketOverlayCount}건`} status="healthy" />
            <StatusCard title="event_overlay" value={`${eventOverlayCount}건`} status="healthy" />
          </div>

          {KNOWN_BUCKETS.map((bucket) => (
            <Panel key={bucket} title={`${BUCKET_LABEL[bucket]} (${sourceTypeCount(data.source_type_counts, bucket)}건)`}>
              <DataTable
                columns={itemColumns}
                data={itemsForBucket(data.items, bucket)}
                idKey="symbol"
                compact
                emptyMessage={`이 날짜에는 ${BUCKET_LABEL[bucket]} 선정 종목이 없습니다(0건).`}
              />
            </Panel>
          ))}

          <details className="rounded-xl border border-[#e2e8f0] bg-white">
            <summary className="cursor-pointer px-5 py-4 text-sm font-medium text-[#475569]">
              기타(reconciliation_overlay / held_position / manual 등) — {otherBucketCount}건
            </summary>
            <div className="px-5 pb-5">
              <DataTable
                columns={otherItemColumns}
                data={otherItems(data.items)}
                idKey="symbol"
                compact
                emptyMessage="기타 source_type 종목이 없습니다."
              />
            </div>
          </details>
        </div>
      )}
    </div>
  );
}
