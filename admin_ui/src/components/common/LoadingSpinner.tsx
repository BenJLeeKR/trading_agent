export function LoadingSpinner({ text = "Loading..." }: { text?: string }) {
  return (
    <div style={{ padding: "2rem", textAlign: "center" }}>
      <article aria-busy={true}>{text}</article>
    </div>
  );
}
