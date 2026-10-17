import { useIsFetching, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  Clock,
  Folder,
  Image as ImageIcon,
  Link2,
  LogOut,
  RefreshCw,
  Search,
  ShieldCheck,
  Star,
  Trash2,
  UserPlus,
  type LucideIcon,
} from "lucide-react";
import { useState, type FormEvent } from "react";
import { NavLink, Outlet, useNavigate, useSearchParams } from "react-router-dom";

import { getUsage } from "../api/library";
import { useAuth } from "../auth/AuthContext";
import { formatBytes } from "../lib/format";
import { MediaProvider } from "../media/MediaContext";
import { Logo } from "./Logo";
import { THEMES, isThemeId, useTheme } from "../theme/ThemeContext";
import { UploadProvider } from "../uploads/UploadContext";
import { UploadPanel } from "./UploadPanel";

const NAV: { to: string; label: string; icon: LucideIcon }[] = [
  { to: "/files", label: "My files", icon: Folder },
  { to: "/photos", label: "Photos", icon: ImageIcon },
  { to: "/favorites", label: "Favorites", icon: Star },
  { to: "/recent", label: "Recent", icon: Clock },
  { to: "/shares", label: "Shared links", icon: Link2 },
  { to: "/invites", label: "Invites", icon: UserPlus },
  { to: "/security", label: "Security", icon: ShieldCheck },
  { to: "/activity", label: "Activity", icon: Activity },
  { to: "/trash", label: "Trash", icon: Trash2 },
];

/** Reloads whatever is on screen. Also spins while any background refresh is running. */
function RefreshButton() {
  const queryClient = useQueryClient();
  const busy = useIsFetching() > 0;
  return (
    <button
      type="button"
      onClick={() => void queryClient.invalidateQueries()}
      aria-label="Refresh"
      title="Refresh"
      className="border border-gray-300 p-2 text-gray-700 hover:bg-gray-100 rounded-md"
    >
      <RefreshCw size={16} aria-hidden className={busy ? "animate-spin" : ""} />
    </button>
  );
}

function UsageMeter() {
  const usage = useQuery({ queryKey: ["usage"], queryFn: getUsage, refetchInterval: 60_000 });
  if (!usage.data) return null;
  const { used_bytes: used, quota_bytes: quota } = usage.data;
  const pct = quota > 0 ? Math.min(100, Math.round((used / quota) * 100)) : 0;
  return (
    <div className="text-xs text-gray-500">
      <div
        role="progressbar"
        aria-label="Storage used"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
        className="h-1.5 w-full overflow-hidden border border-gray-300 bg-gray-100"
      >
        <div className={`h-full ${pct >= 90 ? "bg-red-600" : "bg-blue-600"}`} style={{ width: `${pct}%` }} />
      </div>
      <p className="mt-1">
        {formatBytes(used)} of {formatBytes(quota)} used
      </p>
    </div>
  );
}

export function AppShell() {
  const { user, logout } = useAuth();
  const { theme, setTheme } = useTheme();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [query, setQuery] = useState(params.get("q") ?? "");

  function submitSearch(event: FormEvent) {
    event.preventDefault();
    const text = query.trim();
    navigate(text ? `/files?q=${encodeURIComponent(text)}` : "/files");
  }

  const linkClass = ({ isActive }: { isActive: boolean }) =>
    `flex items-center gap-2 whitespace-nowrap px-3 py-2 text-sm rounded-md ${
      isActive ? "bg-gray-900 text-white" : "text-gray-700 hover:bg-gray-100"
    }`;

  return (
    <MediaProvider>
      <UploadProvider>
        <div className="flex min-h-screen flex-col md:flex-row">
          <aside className="shrink-0 border-b border-gray-200 bg-white md:w-56 md:border-b-0 md:border-r">
            <div className="flex items-center justify-between px-4 py-3 md:block">
              <span className="flex items-center gap-2 text-base font-semibold text-gray-900">
                <Logo size={28} />
                Choud
              </span>
              <span className="truncate text-xs text-gray-500 md:mt-1 md:block" title={user?.email}>
                {user?.email}
              </span>
            </div>
            <nav aria-label="Main" className="flex gap-1 overflow-x-auto px-2 pb-2 md:block md:space-y-1 md:pb-0">
              {NAV.map((item) => (
                <NavLink key={item.to} to={item.to} className={linkClass}>
                  <item.icon size={16} aria-hidden />
                  {item.label}
                </NavLink>
              ))}
            </nav>
            <div className="hidden space-y-4 px-4 py-4 md:block">
              <UsageMeter />
              <label className="block text-xs text-gray-500">
                Theme
                <select
                  value={theme}
                  onChange={(event) => isThemeId(event.target.value) && setTheme(event.target.value)}
                  className="mt-1 w-full border border-gray-300 bg-white px-2 py-1.5 text-sm text-gray-900 rounded-md"
                >
                  {THEMES.map((option) => (
                    <option key={option.id} value={option.id}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
              <button
                onClick={() => void logout()}
                className="flex w-full items-center justify-center gap-2 border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-100 rounded-md"
              >
                <LogOut size={14} aria-hidden />
                Log out
              </button>
            </div>
          </aside>

          <div className="flex min-w-0 flex-1 flex-col">
            <header className="flex items-center gap-2 border-b border-gray-200 bg-white px-4 py-2">
              <form onSubmit={submitSearch} role="search" className="flex flex-1 gap-2">
                <input
                  type="search"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="Search files and folders…"
                  aria-label="Search"
                  className="w-full max-w-xl border border-gray-300 bg-white px-3 py-1.5 text-sm text-gray-900 rounded-md"
                />
                <button
                  type="submit"
                  className="flex items-center gap-2 border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-100 rounded-md"
                >
                  <Search size={14} aria-hidden />
                  Search
                </button>
              </form>
              <RefreshButton />
              <div className="flex items-center gap-2 md:hidden">
                <select
                  aria-label="Theme"
                  value={theme}
                  onChange={(event) => isThemeId(event.target.value) && setTheme(event.target.value)}
                  className="border border-gray-300 bg-white px-1 py-1.5 text-xs text-gray-900 rounded-md"
                >
                  {THEMES.map((option) => (
                    <option key={option.id} value={option.id}>
                      {option.label}
                    </option>
                  ))}
                </select>
                <button onClick={() => void logout()} className="text-xs text-gray-600 hover:underline">
                  Log out
                </button>
              </div>
            </header>
            <main className="min-w-0 flex-1">
              <Outlet />
            </main>
          </div>
        </div>
        <UploadPanel />
      </UploadProvider>
    </MediaProvider>
  );
}
