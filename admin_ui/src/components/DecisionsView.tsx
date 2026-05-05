import { useEffect, useMemo, useState } from "react";
import type { DecisionContextDetail, TradeDecisionDetail } from "../types/api";
import { getDecisionContext, getTradeDecisions } from "../api/client";
import { DataTable } from "./common/DataTable";
import { StatusBadge } from "./common/StatusBadge";
import { ErrorBanner } from "./common/ErrorBanner";
import { LoadingSpinner } from "./common/LoadingSpinner";
import type { Column } from "./common/DataTable";

const SIDES = ["all", "buy", "sell", "hold"] as const;

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
        <span
          style={{
            color:
              r.side.toLowerCase() === "buy"
                ? "var(--pico-ins-color)"
                : "var(--pico-del-color)",
            fontWeight: 600,
          }}
        >
          {r.side.toUpperCase()}
        </span>
      ),
    },
    { key: "intent", label: "Intent" },
    { key: "qty", label: "Qty" },
    {
      key: "confidence",
      label: "Confidence",
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
        <code style={{ fontSize: "0.75rem" }}>
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
        <label>
          Symbol
          <input
            type="search"
            placeholder="Search by ticker..."
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            aria-label="Search decisions by ticker"
            style={{ width: "160px" }}
          />
        </label>
        <label>
          Side
          <select
            value={sideFilter}
            onChange={(e) => setSideFilter(e.target.value)}
            aria-label="Filter by side"
            style={{ width: "120px" }}
          >
            {SIDES.map((s) => (
              <option key={s} value={s}>
                {s === "all" ? "All Sides" : s}
              </option>
            ))}
          </select>
        </label>
        <label>
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
            style={{ width: "100px" }}
          />
        </label>
        <label>
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
            style={{ width: "100px" }}
          />
        </label>
      </div>

      <DataTable
        columns={columns}
        data={filteredDecisions}
        keyField="trade_decision_id"
        onRowClick={(row) => setSelectedDecision(row)}
        selectedKey={selectedDecision?.trade_decision_id ?? null}
        isLoading={loading}
        emptyMessage="No trade decisions found."
      />

      {/* Detail panel */}
      {selectedDecision ? (
        <article className="detail-panel">
          <header>
            <strong>Decision Detail</strong>
            <button
              style={{ float: "right", padding: "0.25rem 0.75rem" }}
              onClick={handleCloseDetail}
              aria-label="Close detail panel"
              type="button"
            >
              ✕
            </button>
          </header>
          <div className="data-grid-2">
            <div>
              <strong>Ticker:</strong> {selectedDecision.ticker}
            </div>
            <div>
              <strong>Side:</strong>{" "}
              <StatusBadge status={selectedDecision.side.toUpperCase()} />
            </div>
            <div>
              <strong>Confidence:</strong>{" "}
              {(selectedDecision.confidence * 100).toFixed(0)}%
            </div>
            <div>
              <strong>Agent:</strong> {selectedDecision.agent_label}
            </div>
            <div>
              <strong>Intent:</strong> {selectedDecision.intent}
            </div>
            <div>
              <strong>Created:</strong>{" "}
              {new Date(selectedDecision.created_at).toLocaleString()}
            </div>
            <div>
              <strong>Decision ID:</strong>{" "}
              <code>{selectedDecision.trade_decision_id}</code>
            </div>
            <div>
              <strong>Context ID:</strong>{" "}
              <code>{selectedDecision.decision_context_id}</code>
            </div>
          </div>

          {contextLoading && <LoadingSpinner text="Loading context..." />}
          {contextError && (
            <ErrorBanner
              message={contextError}
              onDismiss={() => setContextError(null)}
            />
          )}
          {contextDetail && (
            <section className="detail-context-section">
              <h6>Decision Context</h6>
              <div className="data-grid-2">
                <div>
                  <strong>Strategy:</strong> {contextDetail.strategy_code}
                </div>
                <div>
                  <strong>Client:</strong> {contextDetail.client_id}
                </div>
                <div>
                  <strong>Session:</strong> {contextDetail.session_id}
                </div>
                <div>
                  <strong>Agents:</strong> {contextDetail.agent_count}
                </div>
                <div>
                  <strong>Timestamp:</strong>{" "}
                  {new Date(contextDetail.timestamp).toLocaleString()}
                </div>
              </div>
            </section>
          )}
        </article>
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
