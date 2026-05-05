import { useEffect, useMemo, useState } from "react";
import type { DecisionContextDetail, TradeDecisionDetail } from "../types/api";
import { getDecisionContext, getTradeDecisions } from "../api/client";
import { DataTable } from "./common/DataTable";
import { Panel } from "./common/Panel";
import { DetailField } from "./common/DetailField";
import { SectionDivider } from "./common/SectionDivider";
import { StatusBadge } from "./common/StatusBadge";
import { ErrorBanner } from "./common/ErrorBanner";
import { LoadingSpinner } from "./common/LoadingSpinner";
import type { Column } from "./common/DataTable";

const SIDES = ["all", "buy", "sell", "hold"] as const;

/* ───────────────────────────────────────────
 * FilterGroup — single-select button group
 * ─────────────────────────────────────────── */
function FilterGroup({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: { label: string; value: string }[];
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="filter-group" role="group" aria-label={label}>
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          className={`filter-group-btn${value === opt.value ? " filter-group-btn--active" : ""}`}
          onClick={() => onChange(opt.value)}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

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
        !searchText || d.ticker.toLowerCase().includes(searchText.toLowerCase());
      const min = confidenceMin ? parseFloat(confidenceMin) : 0;
      const max = confidenceMax ? parseFloat(confidenceMax) : 1;
      const matchConfidence = d.confidence >= min && d.confidence <= max;
      return matchSide && matchSearch && matchConfidence;
    });
  }, [decisions, searchText, sideFilter, confidenceMin, confidenceMax]);

  const columns: Column<TradeDecisionDetail>[] = [
    { key: "created_at", label: "Created" },
    { key: "ticker", label: "Ticker" },
    {
      key: "side",
      label: "Side",
      render: (r) => (
        <span className={r.side.toLowerCase() === "buy" ? "side-buy" : "side-sell"}>
          {r.side.toUpperCase()}
        </span>
      ),
    },
    { key: "intent", label: "Intent" },
    { key: "qty", label: "Qty" },
    {
      key: "confidence",
      label: "Confidence",
      /* ⚠️ Inline style 보존 — decisions.test.tsx의 toHaveStyle 검증과 연결됨 */
      render: (r) => {
        const pct = (r.confidence * 100).toFixed(0);
        const color =
          r.confidence >= 0.7
            ? "var(--pico-ins-color)"
            : r.confidence >= 0.4
              ? "var(--pico-warning)"
              : "var(--pico-del-color)";
        return <span style={{ color, fontWeight: 600 }}>{pct}%</span>;
      },
    },
    { key: "agent_label", label: "Agent" },
    {
      key: "decision_context_id",
      label: "Context ID",
      render: (r) => (
        <code className="context-id">
          {r.decision_context_id.substring(0, 8)}…
        </code>
      ),
    },
  ];

  if (loading) return <LoadingSpinner />;
  if (error) return <ErrorBanner message={error} onDismiss={() => setError(null)} />;

  function handleCloseDetail() {
    setSelectedDecision(null);
    setContextDetail(null);
  }

  return (
    <section>
      <div className="page-header">
        <h2>Trade Decisions</h2>
        <p>
          Total: {decisions.length} decision{decisions.length !== 1 ? "s" : ""}
        </p>
      </div>

      {/* Filter bar */}
      <div className="filter-bar">
        <input
          type="search"
          placeholder="Search by ticker..."
          value={searchText}
          onChange={(e) => setSearchText(e.target.value)}
          aria-label="Search decisions by ticker"
          style={{ width: "160px" }}
        />

        <FilterGroup
          label="Side"
          options={SIDES.map((s) => ({
            label: s === "all" ? "All" : s.charAt(0).toUpperCase() + s.slice(1),
            value: s,
          }))}
          value={sideFilter}
          onChange={setSideFilter}
        />

        <label className="confidence-filter">
          Confidence Min
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
        <label className="confidence-filter">
          Confidence Max
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

      <Panel
        title="Trade Decisions"
        headerRight={
          <span className="panel-counter">
            {filteredDecisions.length} / {decisions.length} decision
            {decisions.length !== 1 ? "s" : ""}
          </span>
        }
      >
        <DataTable
          columns={columns}
          data={filteredDecisions}
          keyField="trade_decision_id"
          onRowClick={(row) => setSelectedDecision(row)}
          selectedKey={selectedDecision?.trade_decision_id ?? null}
          isLoading={loading}
          emptyMessage="No trade decisions found."
          compact
        />
      </Panel>

      {/* Detail panel */}
      {selectedDecision ? (
        <Panel
          title="Decision Detail"
          subtitle={`${selectedDecision.ticker} · ${selectedDecision.side.toUpperCase()} · ${(selectedDecision.confidence * 100).toFixed(0)}% confidence`}
          headerRight={
            <button
              style={{ padding: "0.25rem 0.75rem", cursor: "pointer" }}
              onClick={handleCloseDetail}
              aria-label="Close detail panel"
              type="button"
            >
              ✕
            </button>
          }
        >
          <div className="detail-grid">
            <DetailField label="Ticker" value={selectedDecision.ticker} />
            <DetailField
              label="Side"
              value={<StatusBadge status={selectedDecision.side.toUpperCase()} />}
            />
            <DetailField
              label="Confidence"
              value={`${(selectedDecision.confidence * 100).toFixed(0)}%`}
            />
            <DetailField label="Agent" value={selectedDecision.agent_label} />
            <DetailField label="Intent" value={selectedDecision.intent} />
            <DetailField
              label="Created"
              value={new Date(selectedDecision.created_at).toLocaleString()}
            />
            <DetailField
              label="Decision ID"
              value={selectedDecision.trade_decision_id}
              mono
            />
            <DetailField
              label="Context ID"
              value={selectedDecision.decision_context_id}
              mono
            />
          </div>

          {contextLoading && <LoadingSpinner text="Loading context..." />}
          {contextError && (
            <ErrorBanner
              message={contextError}
              onDismiss={() => setContextError(null)}
            />
          )}
          {contextDetail && (
            <>
              <SectionDivider label="Decision Context" />
              <div className="detail-grid">
                <DetailField label="Strategy" value={contextDetail.strategy_code} />
                <DetailField label="Client" value={contextDetail.client_id} />
                <DetailField label="Session" value={contextDetail.session_id} />
                <DetailField label="Agents" value={contextDetail.agent_count} />
                <DetailField
                  label="Timestamp"
                  value={new Date(contextDetail.timestamp).toLocaleString()}
                />
              </div>
            </>
          )}
        </Panel>
      ) : (
        !loading &&
        decisions.length > 0 && (
          <article className="placeholder-panel">
            Select a decision row to view details.
          </article>
        )
      )}
    </section>
  );
}
