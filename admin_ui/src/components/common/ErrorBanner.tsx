interface ErrorBannerProps {
  message: string;
  onDismiss?: () => void;
}

export function ErrorBanner({ message, onDismiss }: ErrorBannerProps) {
  return (
    <div
      style={{
        padding: "0.75rem 1rem",
        marginBottom: "1rem",
        backgroundColor: "var(--pico-del-color)",
        color: "#fff",
        borderRadius: "6px",
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
      }}
    >
      <span>⚠ {message}</span>
      {onDismiss && (
        <button
          className="outline"
          onClick={onDismiss}
          style={{ margin: 0, padding: "0.25rem 0.75rem", fontSize: "0.8rem" }}
        >
          Dismiss
        </button>
      )}
    </div>
  );
}
