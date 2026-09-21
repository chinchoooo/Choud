import type { ComponentStatus } from "../types/health";

export function HealthBadge({ label, status }: { label: string; status: ComponentStatus }) {
  const healthy = status === "healthy";
  return (
    <div className="flex items-center justify-between rounded-lg border border-gray-200 px-4 py-3">
      <span className="text-sm font-medium text-gray-700">{label}</span>
      <span
        className={`text-xs font-semibold uppercase tracking-wide ${
          healthy ? "text-green-600" : "text-red-600"
        }`}
      >
        {status}
      </span>
    </div>
  );
}
