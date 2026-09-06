import useSWR from "swr";
import { fetchHealth, HealthResponse } from "@/lib/api";

export function useHealth() {
  const { data, error, isLoading } = useSWR<HealthResponse>(
    "/health",
    fetchHealth,
    {
      refreshInterval: 30000,
      revalidateOnFocus: true,
      shouldRetryOnError: true,
      errorRetryInterval: 10000,
    }
  );

  const available = !!data?.status && !error;
  return { health: data, available, error, isLoading };
}
