export function EmptyState({
  icon = "📭",
  title,
  hint,
  children,
}: {
  icon?: string;
  title: string;
  hint?: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="empty-state">
      <div className="icon" aria-hidden>
        {icon}
      </div>
      <h3>{title}</h3>
      {hint !== undefined && <p style={{ margin: "0 0 12px" }}>{hint}</p>}
      {children}
    </div>
  );
}

export function ErrorState({ message }: { message: string }) {
  return (
    <div className="error-state" role="alert">
      <strong>Something went wrong.</strong>
      <p>{message}</p>
    </div>
  );
}

export function LoadingState({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="loading-state">
      <span className="spinner" aria-hidden />
      <span>{label}</span>
    </div>
  );
}
