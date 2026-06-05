import { type ClassValue, clsx } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/* ───────────────────────────────────────────
 * KST (Asia/Seoul) Timezone Formatters
 *
 * All formatters use fixed Asia/Seoul timezone.
 * Input ISO strings are assumed to be UTC.
 * ─────────────────────────────────────────── */

/** Pre-built KST datetime formatter (full). */
const KST_DATETIME = new Intl.DateTimeFormat("ko-KR", {
  timeZone: "Asia/Seoul",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

/** Pre-built KST date-only formatter (compact). */
const KST_DATE = new Intl.DateTimeFormat("ko-KR", {
  timeZone: "Asia/Seoul",
  month: "2-digit",
  day: "2-digit",
});

/** Pre-built KST time-only formatter (compact). */
const KST_TIME = new Intl.DateTimeFormat("ko-KR", {
  timeZone: "Asia/Seoul",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

/** Pre-built KRW number formatter (no decimal places). */
const KRW_FORMATTER = new Intl.NumberFormat("ko-KR", {
  maximumFractionDigits: 0,
});

export function getKstTodayString(now: Date = new Date()): string {
  const formatter = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
  return formatter.format(now);
}

/**
 * Format an ISO datetime string as a full KST datetime.
 *
 * Input:  ISO string (UTC assumed)
 * Output: `2026-05-15 14:32:44 KST`
 * Null/empty → `"—"`
 */
export function formatKstDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "—";
  const parts = KST_DATETIME.formatToParts(d);
  const y = parts.find((p) => p.type === "year")?.value ?? "";
  const mo = parts.find((p) => p.type === "month")?.value ?? "";
  const dd = parts.find((p) => p.type === "day")?.value ?? "";
  const hh = parts.find((p) => p.type === "hour")?.value ?? "";
  const mm = parts.find((p) => p.type === "minute")?.value ?? "";
  const ss = parts.find((p) => p.type === "second")?.value ?? "";
  return `${y}-${mo}-${dd} ${hh}:${mm}:${ss} KST`;
}

/**
 * Format an ISO datetime string as a compact KST time.
 *
 * Input:  ISO string (UTC assumed)
 * Output: `05-15 14:32`
 * Null/empty → `"—"`
 */
export function formatKstTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "—";
  const dateParts = KST_DATE.formatToParts(d);
  const mo = dateParts.find((p) => p.type === "month")?.value ?? "";
  const dd = dateParts.find((p) => p.type === "day")?.value ?? "";
  const timeParts = KST_TIME.formatToParts(d);
  const hh = timeParts.find((p) => p.type === "hour")?.value ?? "";
  const mm = timeParts.find((p) => p.type === "minute")?.value ?? "";
  return `${mo}-${dd} ${hh}:${mm}`;
}

/**
 * Format a number as KRW with `원` suffix.
 *
 * Input:  `145400`
 * Output: `145,400원`
 * Negative: `-5,000원`
 * Zero:     `0원`
 * Null/NaN → `"—"`
 */
export function formatKrw(val: number | string | null | undefined): string {
  if (val == null) return "—";
  const num = typeof val === "string" ? parseFloat(val) : val;
  if (Number.isNaN(num)) return "—";
  return `${KRW_FORMATTER.format(num)}원`;
}

/**
 * Format an ISO datetime string as KST datetime with elapsed time.
 *
 * Input:  ISO string (UTC assumed)
 * Output: `2026-05-15 14:32:44 KST (3분 전)`
 * Null/empty → `"—"`
 *
 * Elapsed labels:
 *   < 1 min  → 방금 전
 *   < 60 min → N분 전
 *   < 24 hr  → N시간 M분 전
 *   ≥ 24 hr  → N일 전
 */
export function formatKstElapsed(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "—";

  // Absolute KST datetime part
  const parts = KST_DATETIME.formatToParts(d);
  const y = parts.find((p) => p.type === "year")?.value ?? "";
  const mo = parts.find((p) => p.type === "month")?.value ?? "";
  const dd = parts.find((p) => p.type === "day")?.value ?? "";
  const hh = parts.find((p) => p.type === "hour")?.value ?? "";
  const mm = parts.find((p) => p.type === "minute")?.value ?? "";
  const ss = parts.find((p) => p.type === "second")?.value ?? "";
  const absTime = `${y}-${mo}-${dd} ${hh}:${mm}:${ss} KST`;

  // Elapsed time (relative to now)
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  let elapsed = "";
  if (diffMs >= 0) {
    const diffMin = Math.floor(diffMs / 60000);
    if (diffMin < 1) {
      elapsed = "방금 전";
    } else if (diffMin < 60) {
      elapsed = `${diffMin}분 전`;
    } else if (diffMin < 1440) {
      const hours = Math.floor(diffMin / 60);
      const mins = diffMin % 60;
      elapsed = `${hours}시간 ${mins}분 전`;
    } else {
      elapsed = `${Math.floor(diffMin / 1440)}일 전`;
    }
  }

  return `${absTime} (${elapsed})`;
}

/* ───────────────────────────────────────────
 * OrderEvent Reason Code Formatter
 * ─────────────────────────────────────────── */

/**
 * reason_code → 한글 라벨 매핑.
 * 새 reason_code 추가 시 이 맵에 엔트리만 추가하면 됨.
 * stale_cleanup과 broker_truth_recovery는 Phase H에서 추가됨.
 */
const REASON_LABEL_MAP: Record<string, string> = {
  BLOCKED: "차단됨",
  UNCERTAIN: "불확실 상태",
  RECONCILE_RESOLVED: "조정 해소",
  MANUAL_RESOLVE: "운영자 수동 해소",
  manual_paper_resolution: "운영자 수동 해소",
  WS_FILL: "WS 체결 수신",
  FILL_CONFIRMED: "체결 확인",
  REJECTED: "거부됨",
  stale_cleanup: "오래된 상태 정리",
  broker_truth_recovery: "브로커 조회 기반 상태 복구",
};

/** 숫자로만 구성된 문자열인지 판별 (브로커 주문번호) */
const BROKER_ORDER_ID_PATTERN = /^\d+$/;

/**
 * Format an OrderEvent reason_code into a human-readable Korean label.
 *
 * Policy:
 *   1. null / undefined / empty string → "—"
 *   2. Metadata label (fieldMap이 제공된 경우) — 1순위
 *   3. Known code (in REASON_LABEL_MAP) → Korean label (2순위 fallback)
 *   4. Numeric string (broker order ID) → "브로커 주문번호: {value}"
 *   5. Unknown raw code → original value (fallback)
 */
export function formatOrderEventReason(
  code: string | null | undefined,
  fieldMap?: Record<string, string> | null
): string {
  if (code == null || code === "") return "—";
  // 1순위: metadata label (fieldMap이 제공된 경우)
  if (fieldMap && code in fieldMap) return fieldMap[code];
  // 2순위: local fallback map
  if (code in REASON_LABEL_MAP) return REASON_LABEL_MAP[code];
  // 3순위: broker order ID pattern (숫자로만 구성)
  if (BROKER_ORDER_ID_PATTERN.test(code)) return `브로커 주문번호: ${code}`;
  // 4순위: raw fallback
  return code;
}

// ============================================================
// EI (Event Interpretation) Operator-Facing Formatter
// ============================================================

const BIAS_LABEL_MAP: Record<string, string> = {
  neutral: '중립',
  positive: '긍정',
  negative: '부정',
  bearish: '부정', // LLM outlier 정규화
};

const EVIDENCE_STRENGTH_LABEL_MAP: Record<string, string> = {
  none: '없음',
  weak: '약함',
  moderate: '보통',
  strong: '강함',
};

const RELIABILITY_TIER_LABEL_MAP: Record<string, string> = {
  T1: '1등급 (높음)',
  T2: '2등급',
  T3: '3등급',
  T4: '4등급 (낮음)',
};

const IMPACT_DIRECTION_LABEL_MAP: Record<string, string> = {
  positive: '긍정',
  negative: '부정',
  neutral: '중립',
};

const NOVELTY_LABEL_MAP: Record<string, string> = {
  high: '높음',
  medium: '보통',
  low: '낮음',
};

const IMPACT_HORIZON_LABEL_MAP: Record<string, string> = {
  short: '단기',
  swing: '스윙',
  long: '장기',
};

/** 주요 EI reason code 한글 라벨 (상위 30여개 — 나머지는 raw fallback) */
const REASON_CODE_LABEL_MAP: Record<string, string> = {
  // 실적/재무
  earnings_surprise: '실적 서프라이즈',
  earnings_announcement: '실적 발표',
  earnings_release: '실적 발표',
  earnings_report: '실적 보고',
  earnings_filing: '실적 제출',
  quarterly_report: '분기 보고서',
  quarterly_filing: '분기 제출',
  quarterly_report_filed: '분기 보고서 제출',
  quarterly_report_filing: '분기 보고서 제출',
  financial_report: '재무 보고',
  financial_reporting: '재무 보고',
  financial_filing: '재무 제출',
  revenue_growth: '매출 성장',
  // 가격/시장
  price_decline: '가격 하락',
  foreign_investor_selling: '외국인 매도',
  market_share_gain: '시장 점유율 증가',
  etf_inflow: 'ETF 자금 유입',
  etf_listing: 'ETF 상장',
  low_confidence: '신뢰도 낮음',
  low_impact: '영향 낮음',
  low_novelty: '참신성 낮음',
  no_direction: '방향성 없음',
  // 기업 활동
  merger: '합병',
  merger_announcement: '합병 발표',
  merger_decision: '합병 결정',
  merger_report: '합병 보고',
  asset_acquisition: '자산 취득',
  fixed_asset_acquisition: '고정 자산 취득',
  capacity_expansion: '생산 능력 확장',
  capital_expenditure: '자본 지출',
  capital_management: '자본 관리',
  capital_reduction: '자본 감소',
  debt_guarantee: '채무 보증',
  debt_guarantee_increase: '채무 보증 증가',
  debt_guarantee_decision: '채무 보증 결정',
  // 지배구조/규제
  corporate_governance: '지배 구조',
  regulatory_compliance: '규제 준수',
  regulatory_filing: '규제 제출',
  shareholder_return: '주주 환원',
  shareholder_value: '주주 가치',
  shareholding_change: '지분 변동',
  major_shareholder_change: '대주주 변경',
  ownership_change: '소유권 변경',
  strike_risk: '파업 위험',
  labor_dispute: '노동 분쟁',
  operational_disruption: '영업 중단',
  // 데이터 품질
  stale: '오래된 데이터',
  stale_data: '오래된 데이터',
  stale_event: '오래된 이벤트',
  stale_info: '오래된 정보',
  material_event: '중요 이벤트',
  voluntary_disclosure: '자발적 공시',
  fair_disclosure: '공정 공시',
  correction: '정정',
  // IR/커뮤니케이션
  ir_activity: 'IR 활동',
  ir_announcement: 'IR 발표',
  ir_meeting: 'IR 미팅',
  ir_holding: 'IR 개최',
};

export function formatBiasLabel(bias: string | null | undefined): string {
  if (!bias) return '—';
  return BIAS_LABEL_MAP[bias.toLowerCase()] || bias;
}

export function formatConflictLabel(conflict: boolean | null | undefined): string {
  if (conflict === true) return '상반된 이벤트 존재';
  return '—';
}

export function formatReasonCodeLabel(code: string): string {
  const key = code.toLowerCase();
  return REASON_CODE_LABEL_MAP[key] || code;
}

export function formatEvidenceStrength(s: string | null | undefined): string {
  if (!s) return '—';
  return EVIDENCE_STRENGTH_LABEL_MAP[s] || s;
}

export function formatReliabilityTier(tier: string | null | undefined): string {
  if (!tier) return '—';
  return RELIABILITY_TIER_LABEL_MAP[tier] || tier;
}

export function formatImpactDirection(dir: string | null | undefined): string {
  if (!dir) return '—';
  return IMPACT_DIRECTION_LABEL_MAP[dir] || dir;
}

export function formatNovelty(n: string | null | undefined): string {
  if (!n) return '—';
  return NOVELTY_LABEL_MAP[n] || n;
}

export function formatImpactHorizon(h: string | null | undefined): string {
  if (!h) return '—';
  return IMPACT_HORIZON_LABEL_MAP[h] || h;
}

export interface EiInterpretationView {
  biasLabel: string;
  conflictLabel: string;
  reasonCodeLabels: string[];
  reasonCodes: string[];
  evidenceStrengthLabel: string;
  eventCount: number;
  hasMaterialEvents: boolean;
  operatorSummary: string;
  isDegraded: boolean;
  degradedReason: string | null;
  // ★ 신규 Phase 1 필드
  detectedEventCount: number;
  interpretedEventCount: number;
  summaryBasis: string;
  // ★ 신규 Phase 2 필드
  isReconstructed: boolean;
}

export function formatEiOutput(so: Record<string, unknown> | null | undefined): EiInterpretationView | null {
  if (!so) return null;
  const av = so.aggregate_view as Record<string, unknown> | undefined;
  if (!av) return null;

  const bias = av.overall_bias as string | undefined;
  const conflict = av.event_conflict as boolean | undefined;
  const rawReasonCodes = (av.top_reason_codes as string[]) || [];
  const evidenceStrength = av.evidence_strength as string | undefined;
  const eventCount = (av.event_count as number) ?? 0;
  const noMaterialEvents = av.no_material_events as boolean | undefined;
  const events = (so.events as Array<Record<string, unknown>>) ?? [];

  // ★ 신규: 최상위 필드 우선, 없으면 aggregate_view에서 fallback
  const detectedEventCount = (so.detected_event_count as number) ?? eventCount;
  const interpretedEventCount = (so.interpreted_event_count as number) ?? events.length;
  const summaryBasis = (so.summary_basis as string) ?? "none";

  // ★ 모든 events가 is_reconstructed=True인지 확인
  const isReconstructed = events.length > 0 && events.every(
    (ev) => (ev as Record<string, unknown>).is_reconstructed === true
  );

  const biasLabel = formatBiasLabel(bias);
  const conflictLabel = formatConflictLabel(conflict);
  const reasonCodeLabels = rawReasonCodes.map(formatReasonCodeLabel);
  const evidenceStrengthLabel = formatEvidenceStrength(evidenceStrength);

  // Degraded status from aggregate_view
  const interpretationIncomplete = av.interpretation_incomplete as boolean | undefined;
  const degradedReason = av.degraded_reason as string | null | undefined;

  // Generate deterministic operator summary
  const parts: string[] = [`성향: ${biasLabel}`];
  if (conflict) parts.push('상반된 이벤트 존재');
  if (rawReasonCodes.length > 0) {
    parts.push(`사유: ${reasonCodeLabels.slice(0, 3).join(', ')}${rawReasonCodes.length > 3 ? ' 외' : ''}`);
  }
  if (!noMaterialEvents && interpretedEventCount > 0) {
    parts.push(`이벤트 ${interpretedEventCount}건`);
  }
  const operatorSummary = parts.join(' | ');

  return {
    biasLabel,
    conflictLabel,
    reasonCodeLabels,
    reasonCodes: rawReasonCodes,
    evidenceStrengthLabel,
    eventCount: interpretedEventCount,  // eventCount는 interpreted count로 재정의
    hasMaterialEvents: !noMaterialEvents,
    operatorSummary,
    isDegraded: interpretationIncomplete === true,
    degradedReason: degradedReason ?? null,
    // ★ 신규
    detectedEventCount,
    interpretedEventCount,
    summaryBasis,
    isReconstructed,
  };
}
