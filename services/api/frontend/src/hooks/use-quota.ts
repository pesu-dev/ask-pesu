import useSWR from "swr";
import { fetchQuota, QuotaResponse } from "@/lib/api";

export function useQuota() {
  const { data, error, isLoading } = useSWR<QuotaResponse>(
    "/quota",
    fetchQuota,
    {
      refreshInterval: 60000,
      revalidateOnFocus: true,
    }
  );

  const thinkingAvailable = data?.quota?.thinking?.available ?? true;
  const primaryAvailable = data?.quota?.primary?.available ?? true;

  return { quota: data, thinkingAvailable, primaryAvailable, error, isLoading };
}
