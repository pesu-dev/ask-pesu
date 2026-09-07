// Polls /quota so a model already in cooldown can be disabled in the UI, instead
// of letting the user send a question that is certain to come back 429.
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
