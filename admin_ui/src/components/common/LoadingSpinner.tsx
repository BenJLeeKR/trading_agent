export function LoadingSpinner({ text = "Loading..." }: { text?: string }) {
  return (
    <div className="loading-spinner">
      <div className="loading-spinner-indicator" />
      <p>{text}</p>
    </div>
  );
}
