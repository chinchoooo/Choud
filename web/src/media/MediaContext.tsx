import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { fetchMediaToken, mediaContentUrl, mediaThumbUrl } from "../api/library";

interface MediaContextValue {
  /** True once a media token is available; before that, URLs are null. */
  ready: boolean;
  contentUrl: (fileId: string) => string | null;
  thumbUrl: (fileId: string, size?: 128 | 256 | 512 | 1024) => string | null;
}

const MediaContext = createContext<MediaContextValue | undefined>(undefined);

// `<img>` and `<video>` tags cannot send an Authorization header, so previews use a
// short-lived, read-only token in the URL. It is renewed well before it expires.
const RENEW_FRACTION = 0.7;
const RETRY_MS = 15_000;

export function MediaProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    async function renew() {
      try {
        const response = await fetchMediaToken();
        if (cancelled) return;
        setToken(response.token);
        timer = setTimeout(() => void renew(), response.expires_in * 1000 * RENEW_FRACTION);
      } catch {
        if (!cancelled) timer = setTimeout(() => void renew(), RETRY_MS);
      }
    }

    void renew();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, []);

  const value = useMemo<MediaContextValue>(
    () => ({
      ready: token !== null,
      contentUrl: (fileId) => (token ? mediaContentUrl(token, fileId) : null),
      thumbUrl: (fileId, size = 256) => (token ? mediaThumbUrl(token, fileId, size) : null),
    }),
    [token],
  );

  return <MediaContext.Provider value={value}>{children}</MediaContext.Provider>;
}

export function useMedia(): MediaContextValue {
  const context = useContext(MediaContext);
  if (!context) throw new Error("useMedia must be used inside <MediaProvider>");
  return context;
}
