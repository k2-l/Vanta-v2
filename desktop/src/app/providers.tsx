import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

/**
 * 应用级 Provider——服务端状态交给 TanStack Query（方案 §12.1）。
 * 本地 UI/连接状态走 Zustand，不放这里。
 */
export function AppProviders({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 15_000,
            retry: (count, err) => {
              // 归一化 ClientError：仅 retryable 者重试，最多 2 次。
              const retryable = (err as { retryable?: boolean } | null)?.retryable;
              return retryable === true && count < 2;
            },
            refetchOnWindowFocus: false,
          },
        },
      }),
  );

  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
