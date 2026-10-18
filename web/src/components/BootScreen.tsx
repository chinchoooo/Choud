import { Check, CircleAlert, Loader } from "lucide-react";

import { Logo } from "./Logo";

export type StepState = "pending" | "active" | "done" | "failed";

export interface BootStep {
  label: string;
  state: StepState;
  /** A short, honest note: what was found, or what went wrong. */
  detail?: string;
}

function Mark({ state }: { state: StepState }) {
  if (state === "done") return <Check size={14} aria-hidden />;
  if (state === "failed") return <CircleAlert size={14} aria-hidden />;
  if (state === "active") return <Loader size={14} aria-hidden className="motion-safe:animate-spin" />;
  return <span aria-hidden className="inline-block h-3.5 w-3.5 border border-gray-400" />;
}

/**
 * Shown while the app starts. Every step reflects something that really happens (the server
 * answering, the saved login being checked): nothing here is on a timer. Motion respects the
 * "reduce motion" setting.
 */
export function BootScreen({ steps, onRetry }: { steps: BootStep[]; onRetry?: () => void }) {
  const failed = steps.some((step) => step.state === "failed");
  const done = steps.filter((step) => step.state === "done").length;
  return (
    <div
      role="status"
      aria-live="polite"
      aria-label="Starting Choud"
      className="flex min-h-screen flex-col items-center justify-center bg-white p-8 text-gray-900"
    >
      <Logo variant="full" size={200} />
      <h1 className="sr-only">Choud</h1>
      <ol className="mt-6 w-full max-w-xs space-y-2 text-sm">
        {steps.map((step) => (
          <li key={step.label} className={`flex items-start gap-2 ${step.state === "pending" ? "text-gray-400" : ""}`}>
            <span className="mt-0.5">
              <Mark state={step.state} />
            </span>
            <span>
              {step.label}
              {step.detail && <span className="block text-xs text-gray-500">{step.detail}</span>}
            </span>
          </li>
        ))}
      </ol>
      <div
        role="progressbar"
        aria-label="Startup progress"
        aria-valuemin={0}
        aria-valuemax={steps.length}
        aria-valuenow={done}
        className="mt-5 flex w-full max-w-xs gap-0.5 border-2 border-gray-900 p-1"
      >
        {Array.from({ length: 18 }, (_, index) => {
          const filled = steps.length > 0 && index < Math.round((done / steps.length) * 18);
          return <span key={index} className={`h-4 flex-1 ${filled ? "bg-gray-900" : "bg-transparent"}`} />;
        })}
      </div>
      {failed && onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-5 border border-gray-900 bg-gray-900 px-4 py-1.5 text-sm text-white"
        >
          Try again
        </button>
      )}
    </div>
  );
}
