import { Navigate, Outlet, useLocation } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import { useHealth } from "../hooks/useHealth";
import { BootScreen, type BootStep } from "./BootScreen";

/** The startup steps, each taken from something that actually happened. */
function useBootSteps(): { steps: BootStep[]; retry: () => void } {
  const { isLoading, bootError, retryBoot } = useAuth();
  const health = useHealth();

  const server: BootStep = health.isError
    ? { label: "Reaching the server", state: "failed", detail: "No answer yet. Is the server on, and are you on its network?" }
    : health.isSuccess
      ? {
          label: "Reaching the server",
          state: "done",
          detail: health.data.status === "healthy" ? undefined : `Running, but ${health.data.status}.`,
        }
      : { label: "Reaching the server", state: "active" };

  const session: BootStep = bootError
    ? { label: "Checking your login", state: "failed", detail: bootError }
    : isLoading
      ? { label: "Checking your login", state: server.state === "failed" ? "pending" : "active" }
      : { label: "Checking your login", state: "done" };

  return {
    steps: [server, session],
    retry: () => {
      void health.refetch();
      retryBoot();
    },
  };
}

export function ProtectedRoute() {
  const { user, isLoading, bootError } = useAuth();
  const location = useLocation();
  const { steps, retry } = useBootSteps();

  if (isLoading || bootError) {
    return <BootScreen steps={steps} onRetry={retry} />;
  }

  if (!user) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  return <Outlet />;
}
