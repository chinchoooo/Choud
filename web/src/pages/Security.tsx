import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { ApiError } from "../api/client";
import { getSecurityLog } from "../api/insights";
import {
  disableTwoFactor,
  enableTwoFactor,
  getTwoFactorStatus,
  newRecoveryCodes,
  startTwoFactor,
  type TwoFactorSetup,
} from "../api/twofactor";
import { plainButton, primaryButton } from "../components/Dialogs";
import { QrCode } from "../components/QrCode";
import { formatDateTime } from "../lib/format";

const field =
  "mt-1 block w-56 rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900";

function message(error: unknown): string | null {
  if (!error) return null;
  return error instanceof ApiError ? error.message : "Something went wrong.";
}

function RecoveryCodes({ codes, onDone }: { codes: string[]; onDone: () => void }) {
  return (
    <div className="mt-4 rounded-md border border-gray-300 p-4">
      <p className="text-sm font-medium text-gray-900">Save these recovery codes now</p>
      <p className="mt-1 text-sm text-gray-600">
        Each one works once if you lose your phone. They will not be shown again.
      </p>
      <ul className="mt-3 grid grid-cols-2 gap-1 font-mono text-sm text-gray-900" aria-label="Recovery codes">
        {codes.map((code) => (
          <li key={code}>{code}</li>
        ))}
      </ul>
      <button className={`${primaryButton} mt-3`} onClick={onDone}>
        I have saved them
      </button>
    </div>
  );
}

/** Turn authenticator-app login on or off, and manage recovery codes. */
export function Security() {
  const queryClient = useQueryClient();
  const status = useQuery({ queryKey: ["2fa"], queryFn: getTwoFactorStatus });
  const log = useQuery({ queryKey: ["security-log"], queryFn: getSecurityLog });
  const [setup, setSetup] = useState<TwoFactorSetup | null>(null);
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [codes, setCodes] = useState<string[] | null>(null);
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["2fa"] });

  const start = useMutation({ mutationFn: startTwoFactor, onSuccess: setSetup });
  const enable = useMutation({
    mutationFn: () => enableTwoFactor(code.trim()),
    onSuccess: (result) => {
      setSetup(null);
      setCode("");
      setCodes(result.recovery_codes);
      refresh();
    },
  });
  const regenerate = useMutation({
    mutationFn: () => newRecoveryCodes(code.trim()),
    onSuccess: (result) => {
      setCode("");
      setCodes(result.recovery_codes);
      refresh();
    },
  });
  const disable = useMutation({
    mutationFn: () => disableTwoFactor(password, code.trim()),
    onSuccess: () => {
      setCode("");
      setPassword("");
      refresh();
    },
  });

  const enabled = status.data?.enabled ?? false;
  const error = message(start.error ?? enable.error ?? regenerate.error ?? disable.error);

  return (
    <div className="max-w-xl p-6">
      <h1 className="text-xl font-semibold text-gray-900">Security</h1>
      <h2 className="mt-4 text-sm font-medium text-gray-900">Two-factor login</h2>
      <p className="mt-1 text-sm text-gray-600">
        {enabled
          ? "On. Logging in needs a code from your authenticator app as well as your password."
          : "Off. Turn it on so a stolen password alone cannot open your files."}
      </p>

      {codes && <RecoveryCodes codes={codes} onDone={() => setCodes(null)} />}

      {!enabled && !setup && !codes && (
        <button className={`${primaryButton} mt-3`} onClick={() => start.mutate()} disabled={start.isPending}>
          Turn on two-factor login
        </button>
      )}

      {setup && (
        <form
          className="mt-4"
          onSubmit={(event) => {
            event.preventDefault();
            enable.mutate();
          }}
        >
          <p className="text-sm text-gray-700">
            Scan this with an authenticator app (Google Authenticator, Aegis, 1Password...), then type the 6-digit
            code it shows.
          </p>
          <div className="mt-3">
            <QrCode text={setup.otpauth_uri} label="QR code for your authenticator app" />
          </div>
          <p className="mt-2 text-xs text-gray-500">
            Cannot scan? Enter this key by hand: <code className="font-mono text-gray-900">{setup.secret}</code>
          </p>
          <label className="mt-3 block text-sm text-gray-700">
            6-digit code
            <input
              value={code}
              onChange={(event) => setCode(event.target.value)}
              inputMode="numeric"
              autoComplete="one-time-code"
              className={field}
            />
          </label>
          <div className="mt-3 flex gap-2">
            <button type="submit" className={primaryButton} disabled={enable.isPending || code.trim().length < 6}>
              Confirm and turn on
            </button>
            <button type="button" className={plainButton} onClick={() => setSetup(null)}>
              Cancel
            </button>
          </div>
        </form>
      )}

      {enabled && !codes && (
        <div className="mt-4">
          <p className="text-sm text-gray-600">
            {status.data?.recovery_codes_left ?? 0} recovery code(s) left.
          </p>
          <label className="mt-3 block text-sm text-gray-700">
            Current code
            <input
              value={code}
              onChange={(event) => setCode(event.target.value)}
              inputMode="numeric"
              autoComplete="one-time-code"
              className={field}
            />
          </label>
          <label className="mt-3 block text-sm text-gray-700">
            Password (needed to turn it off)
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
              className={field}
            />
          </label>
          <div className="mt-3 flex flex-wrap gap-2">
            <button className={plainButton} disabled={!code.trim() || regenerate.isPending} onClick={() => regenerate.mutate()}>
              Make new recovery codes
            </button>
            <button
              className={plainButton}
              disabled={!code.trim() || !password || disable.isPending}
              onClick={() => disable.mutate()}
            >
              Turn off
            </button>
          </div>
        </div>
      )}

      {error && (
        <p role="alert" className="mt-3 text-sm text-red-600">
          {error}
        </p>
      )}

      <h2 className="mt-8 text-sm font-medium text-gray-900">Recent sign-ins</h2>
      <p className="mt-1 text-sm text-gray-600">
        Attempts to sign in to your account. If you see one you do not recognise, change your password.
      </p>
      <ul className="mt-2 divide-y divide-gray-200 border border-gray-200 bg-white rounded-md" aria-label="Sign-in history">
        {(log.data ?? []).length === 0 && <li className="p-3 text-sm text-gray-500">Nothing recorded yet.</li>}
        {(log.data ?? []).map((event, index) => (
          <li key={index} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-sm">
            <span className={event.success ? "text-gray-900" : "font-semibold text-red-600"}>
              {event.success ? "Signed in" : "Failed attempt"}
            </span>
            {event.new_device && <span className="border border-gray-400 px-1.5 text-xs text-gray-900">new device</span>}
            <span className="text-xs text-gray-500">{formatDateTime(event.at)}</span>
            <span className="text-xs text-gray-500">{event.ip || "unknown address"}</span>
            <span className="min-w-0 flex-1 truncate text-xs text-gray-400" title={event.user_agent}>
              {event.user_agent}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
