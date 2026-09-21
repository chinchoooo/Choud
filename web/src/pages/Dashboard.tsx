import { Link } from "react-router-dom";

import { useHealth } from "../hooks/useHealth";
import { HealthBadge } from "../components/HealthBadge";

export function Dashboard() {
  const { data, isLoading, isError } = useHealth();

  return (
    <div className="mx-auto max-w-2xl p-8">
      <h1 className="text-2xl font-semibold text-gray-900">My Cloud</h1>
      <p className="mt-1 text-sm text-gray-500">
        System status. Head to{" "}
        <Link to="/files" className="font-medium text-gray-900 underline">
          your files
        </Link>{" "}
        (or{" "}
        <Link to="/login" className="font-medium text-gray-900 underline">
          log in
        </Link>{" "}
        first) to manage folders and uploads.
      </p>

      <div className="mt-6 space-y-2">
        {isLoading && <p className="text-sm text-gray-500">Checking system health…</p>}
        {isError && (
          <p className="text-sm text-red-600">Could not reach the backend API.</p>
        )}
        {data && (
          <>
            <HealthBadge label="API" status={data.status} />
            <HealthBadge label="Database" status={data.database} />
            <HealthBadge label="Engine" status={data.engine} />
            <HealthBadge label="Storage" status={data.storage} />
          </>
        )}
      </div>
    </div>
  );
}
