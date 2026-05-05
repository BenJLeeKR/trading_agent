import { useEffect, useMemo, useState } from "react";
import type { DecisionContextDetail, TradeDecisionDetail } from "../types/api";
import { getDecisionContext, getTradeDecisions } from "../api/client";
import { DataTable } from "./common/DataTable";
import { StatusBadge } from "./common/StatusBadge";
import { ErrorBanner } from "./common/ErrorBanner";
import { LoadingSpinner } from "./common/LoadingSpinner";
import type { Column } from "./common/DataTable";
import { X, Brain, TrendingUp, TrendingDown, Search } from "lucide-react";

const SIDES = ["all", "buy", "sell", "hold"] as const;

/* ───────────────────────────────────────────
 * ConfidenceBar — progress bar with color threshold
 * ─────────────────────────────────────────── */
function ConfidenceBar({ value }: { value: number }) {
  // value is 0–1 float; convert to 0–100
  const pct = value * 100;
  const color = value >= 0.7 ? "#22c55e" : value >= 0.4 ? "#f59e0b" : "#ef4444";
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 rounded-full overflow-hidden" style={{ backgroundColor: "#f3f4f6" }}>
        <div
          className="h-full rounded-full transition-all"
          style={{ width: `${pct}%`, backgroundColor: color }}
        />
      </div>
      <span className="text-xs font-semibold tabular-nums shrink-0" style={{ color, minWidth: 32 }}>
        {pct.toFixed(0)}%
      </span>
    </div>
  );
}

/* ───────────────────────────────────────────
 * DetailRow — label + value pair for detail panels
 * ─────────────────────────────────────────── */
function DetailRow({ label, value, valueColor }: { label: string; value: string; valueColor?: string }) {
  return (
    <div className="detail-row">
      <span className="detail-row-label">{label}</span>
      <span className="detail-row-value" style={valueColor ? { color: valueColor } : undefined}>
        {value}
      </span>
    </div>
  );
}

/* ───────────────────────────────────────────
 * DecisionsView
 * ─────────────────────────────────────────── */
export default function DecisionsView() {
  const [decisions, setDecisions] = useState<TradeDecisionDetail[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Selection state
  const [selectedDecision, setSelectedDecision] = useState<TradeDecisionDetail | null>(null);
  const [contextDetail, setContextDetail] = useState<DecisionContextDetail | null>(null);
  const [contextLoading, setContextLoading] = useState(false);
  const [contextError, setContextError] = useState<string | null>(null);

  // Filter state
  const [searchText, setSearchText] = useState("");
  const [sideFilter, setSideFilter] = useState("all");
  const [confidenceMin, setConfidenceMin] = useState("");
  const [confidenceMax, setConfidenceMax] = useState("");

  useEffect(() => {
    setLoading(true);
    setError(null);
    getTradeDecisions()
      .then(setDecisions)
      .catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : "Failed to load trade decisions";
        setError(msg);
      })
      .finally(() => setLoading(false));
  }, []);

  // Lazy-load decision context on row select (with stale-response guard)
  useEffect(() => {
    const contextId = selectedDecision?.decision_context_id;
    if (!contextId) {
      setContextDetail(null);
      return;
    }
    let cancelled = false;
    setContextLoading(true);
    setContextError(null);
    getDecisionContext(contextId)
      .then((result) => {
        if (!cancelled) setContextDetail(result);
      })
      .catch((err) => {
        if (!cancelled) {
          setContextError(err instanceof Error ? err.message : "Failed to load context");
        }
      })
      .finally(() => {
        if (!cancelled) setContextLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedDecision?.decision_context_id]);

  const filteredDecisions = useMemo(() => {
    return decisions.filter((d) => {
      const matchSide = sideFilter === "all" || d.side === sideFilter;
      const matchSearch =
        !searchText || d.symbol.toLowerCase().includes(searchText.toLowerCase());
      const min = confidenceMin ? parseFloat(confidenceMin) : 0;
      const max = confidenceMax ? parseFloat(confidenceMax) : 1;
      const matchConfidence = (d.confidence ?? 0) >= min && (d.confidence ?? 0) <= max;
      return matchSide && matchSearch && matchConfidence;
    });
  }, [decisions, searchText, sideFilter, confidenceMin, confidenceMax]);

  const columns: Column<TradeDecisionDetail>[] = [
    { key: "trade_decision_id", label: "Decision ID", render: (r) => <code>{r.trade_decision_id.slice(0, 8)}…</code> },
    { key: "symbol", label: "Symbol" },
    {
      key: "side",
      label: "Action",
      render: (r) => {
        const color = r.side.toLowerCase() === "buy" ? "#16a34a" : r.side.toLowerCase() === "sell" ? "#dc2626" : "#6b7280";
        return <span style={{ color, fontWeight: 600 }}>{r.side.toUpperCase()}</span>;
      },
    },
    {
      key: "confidence",
      label: "Confidence",
      render: (r) => <ConfidenceBar value={r.confidence ?? 0} />,
    },
    { key: "strategy_id", label: "Strategy" },
    {
      key: "created_at",
      label: "Time",
      render: (r) => new Date(r.created_at).toLocaleTimeString(),
    },
  ];

  if (loading) return <LoadingSpinner />;
  if (error) return <ErrorBanner message={error} onDismiss={() => setError(null)} />;

  return (
    <section>
      <div className="page-header">
        <h2>Trade Decisions</h2>
        <p>
          Total: {decisions.length} decision{decisions.length !== 1 ? "s" : ""}
        </p>
      </div>

      {/* ── Split layout ── */}
      <div className="split-layout">
        {/* Left: filters + table */}
        <div className="split-main">
          {/* Filter bar */}
          <div className="filter-bar">
            <div className="input-wrap">
              <Search size={14} className="input-wrap-icon" />
              <input
                type="search"
                placeholder="Search by ticker..."
                value={searchText}
                onChange={(e) => setSearchText(e.target.value)}
                aria-label="Search decisions by ticker"
              />
            </div>

            <div className="filter-group" role="group" aria-label="Side">
              {SIDES.map((s) => (
                <button
                  key={s}
                  type="button"
                  className={`pill-btn${sideFilter === s ? " pill-btn--active" : ""}`}
                  onClick={() => setSideFilter(s)}
                >
                  {s === "all" ? "All" : s.charAt(0).toUpperCase() + s.slice(1)}
                </button>
              ))}
            </div>

            <div className="flex items-center gap-2 ml-auto">
              <label className="confidence-filter" style={{ fontSize: "0.75rem", color: "#9ca3af" }}>
                Min
                <input
                  type="number"
                  min="0"
                  max="1"
                  step="0.05"
                  placeholder="0.0"
                  value={confidenceMin}
                  onChange={(e) => setConfidenceMin(e.target.value)}
                  aria-label="Minimum confidence"
                  className="confidence-input"
                />
              </label>
              <label className="confidence-filter" style={{ fontSize: "0.75rem", color: "#9ca3af" }}>
                Max
                <input
                  type="number"
                  min="0"
                  max="1"
                  step="0.05"
                  placeholder="1.0"
                  value={confidenceMax}
                  onChange={(e) => setConfidenceMax(e.target.value)}
                  aria-label="Maximum confidence"
                  className="confidence-input"
                />
              </label>
            </div>
          </div>

          {/* Table panel */}
          <div className="card-panel">
            <div className="card-panel-header">
              <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                <Brain size={13} style={{ color: "#374151" }} />
                <span className="card-panel-title">Decision Log</span>
              </div>
              <span className="card-panel-count">
                {filteredDecisions.length} / {decisions.length}
              </span>
            </div>
            <DataTable
              columns={columns}
              data={filteredDecisions}
              keyField="trade_decision_id"
              onRowClick={(row) => setSelectedDecision(
                selectedDecision?.trade_decision_id === row.trade_decision_id ? null : row
              )}
              selectedKey={selectedDecision?.trade_decision_id ?? null}
              emptyMessage="No trade decisions found."
              compact
            />
          </div>
        </div>

        {/* Right: detail panel (288px) */}
        {selectedDecision ? (
          <div className="split-sidebar" style={{ width: 288, flexShrink: 0 }}>
            {/* ── Decision Detail card ── */}
            <div className="card-panel">
              <div className="card-panel-header">
                <span className="card-panel-title">Decision Detail</span>
                <button
                  onClick={() => { setSelectedDecision(null); setContextDetail(null); }}
                  style={{ color: "#9ca3af", background: "none", border: "none", cursor: "pointer", padding: 0 }}
                  aria-label="Close detail panel"
                  type="button"
                >
                  <X size={13} />
                </button>
              </div>

              {/* Action + status banner */}
              <div
                className="status-banner"
                style={{
                  backgroundColor:
                    (selectedDecision.confidence ?? 0) >= 0.7 ? "#f0fdf4" :
                    (selectedDecision.confidence ?? 0) >= 0.4 ? "#fffbeb" :
                    "#fef2f2",
                  borderBottom: "1px solid #e8eaed",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                  <span style={{ fontWeight: 700, fontSize: "0.875rem", color: "#16a34a" }}>
                    {selectedDecision.side.toUpperCase()}
                  </span>
                  <span style={{ fontWeight: 600, fontSize: "0.875rem", color: "#111827" }}>
                    {selectedDecision.symbol}
                  </span>
                </div>
                <span
                  className="status-badge"
                  style={{
                    backgroundColor:
                      (selectedDecision.confidence ?? 0) >= 0.7 ? "#dcfce7" :
                      (selectedDecision.confidence ?? 0) >= 0.4 ? "#fef3c7" :
                      "#fee2e2",
                    color:
                      (selectedDecision.confidence ?? 0) >= 0.7 ? "#16a34a" :
                      (selectedDecision.confidence ?? 0) >= 0.4 ? "#d97706" :
                      "#dc2626",
                  }}
                >
                  <span className="status-badge-dot" />
                  {((selectedDecision.confidence ?? 0) * 100).toFixed(0)}%
                </span>
              </div>

              {/* Fields */}
              <div className="panel-body">
                <DetailRow label="Decision ID" value={selectedDecision.trade_decision_id.slice(0, 16) + "…"} />
                <DetailRow label="Decision Type" value={selectedDecision.decision_type} />
                <DetailRow label="Strategy ID" value={selectedDecision.strategy_id} />
                <DetailRow label="Qty" value={String(selectedDecision.quantity ?? "—")} />
                <DetailRow
                  label="Created"
                  value={new Date(selectedDecision.created_at).toLocaleString()}
                />
                <DetailRow label="Context ID" value={selectedDecision.decision_context_id.slice(0, 12) + "…"} />
              </div>

              {/* Confidence bar */}
              <div style={{ padding: "0 1rem 0.75rem" }}>
                <p style={{ fontSize: "0.75rem", color: "#9ca3af", marginBottom: "0.375rem" }}>Confidence</p>
                <ConfidenceBar value={selectedDecision.confidence ?? 0} />
              </div>

              {/* Reason (rationale_summary) */}
              <div style={{ padding: "0.75rem 1rem", borderTop: "1px solid #f3f4f6" }}>
                <p style={{ fontSize: "0.75rem", fontWeight: 600, color: "#374151", marginBottom: "0.25rem" }}>Reason</p>
                <p style={{ fontSize: "0.75rem", lineHeight: "1.4", color: "#6b7280" }}>
                  {selectedDecision.rationale_summary || "No reason provided."}
                </p>
              </div>
            </div>

            {/* ── Input Signals card ── */}
            <div className="card-panel">
              <div className="card-panel-header">
                <span className="card-panel-title">Input Signals</span>
              </div>
              <div className="panel-body">
                <DetailRow label="Strategy ID" value={selectedDecision.strategy_id} />
                <DetailRow
                  label="Side Signal"
                  value={selectedDecision.side.toUpperCase()}
                  valueColor={
                    selectedDecision.side.toLowerCase() === "buy" ? "#16a34a" :
                    selectedDecision.side.toLowerCase() === "sell" ? "#dc2626" :
                    "#6b7280"
                  }
                />
                <DetailRow label="Confidence Score" value={`${((selectedDecision.confidence ?? 0) * 100).toFixed(0)}%`} />
                <DetailRow label="Quantity" value={String(selectedDecision.quantity ?? "—")} />
              </div>
            </div>

            {/* ── Market Context card ── */}
            <div className="card-panel">
              <div className="card-panel-header">
                <span className="card-panel-title">Market Context</span>
              </div>

              {contextLoading && (
                <div className="panel-body">
                  <LoadingSpinner text="Loading context..." />
                </div>
              )}

              {contextError && (
                <div style={{ padding: "0.5rem" }}>
                  <ErrorBanner message={contextError} onDismiss={() => setContextError(null)} />
                </div>
              )}

              {contextDetail && (
                <div className="panel-body">
                  <DetailRow label="Strategy ID" value={contextDetail.strategy_id} />
                  <DetailRow label="Account ID" value={contextDetail.account_id} />
                  <DetailRow label="Session ID" value={contextDetail.trading_session_id ?? "—"} />
                  <DetailRow label="Config Version" value={contextDetail.config_version_id} />
                  <DetailRow label="Correlation ID" value={contextDetail.correlation_id} />
                  <DetailRow
                    label="Market Timestamp"
                    value={new Date(contextDetail.market_timestamp).toLocaleString()}
                  />
                </div>
              )}

              {!contextDetail && !contextLoading && !contextError && (
                <div style={{ padding: "1rem", textAlign: "center", color: "#9ca3af", fontSize: "0.75rem" }}>
                  Select a decision with context to view market data.
                </div>
              )}
            </div>
          </div>
        ) : (
          !loading && decisions.length > 0 && (
            <div className="split-sidebar" style={{ width: 288, flexShrink: 0 }}>
              <div className="split-main-placeholder" style={{ height: "100%" }}>
                <Brain size={32} />
                <p>Select a decision row to view details.</p>
              </div>
            </div>
          )
        )}
      </div>
    </section>
  );
}
