interface ErrorBannerProps {
  message: string;
  onDismiss?: () => void;
}

export function ErrorBanner({ message, onDismiss }: ErrorBannerProps) {
  return (
    <div className="warning-banner warning-banner--error">
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
