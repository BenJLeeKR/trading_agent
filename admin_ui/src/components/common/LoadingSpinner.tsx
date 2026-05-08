export function LoadingSpinner({ text = "로딩 중..." }: { text?: string }) {
  return (
    <div className="flex flex-col items-center justify-center p-8 gap-3">
      <div className="h-8 w-8 animate-spin rounded-full border-2 border-[#e2e8f0] border-t-[#3b82f6]" />
      <p className="text-sm text-[#64748b]">{text}</p>
    </div>
  );
}
