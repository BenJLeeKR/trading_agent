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
