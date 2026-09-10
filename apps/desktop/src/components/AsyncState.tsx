export function LoadingState({ label = "加载中..." }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 py-6 text-sm text-slate-500">
      <span className="h-2 w-2 animate-pulse rounded-full bg-sky-500" />
      {label}
    </div>
  );
}

export function ErrorState({ message }: { message: string }) {
  return (
    <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
      {message}
    </div>
  );
}