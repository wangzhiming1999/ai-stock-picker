import { useCallback, useEffect, useState } from "react";
import { fetchBriefing } from "../../api/client";
import type { Briefing } from "../../types";

/** 简报取数 + 加载态编排：宿主只负责「拿什么状态、怎么摆」，数据获取收口到这一处。 */
export function useBriefing(onSettled?: () => void) {
  const [data, setData] = useState<Briefing | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setErr("");
    try {
      setData(await fetchBriefing());
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setLoading(false);
      onSettled?.();
    }
  }, [onSettled]);

  useEffect(() => {
    void load();
  }, [load]);

  return { data, loading, err, load };
}
