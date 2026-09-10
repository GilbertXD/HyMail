import { useEffect, useState } from "react";

import { estimateRetrySeconds } from "../../lib/format";

export function RetryCountdown({ attempts }: { attempts: number }) {
  const [remaining, setRemaining] = useState(() =>
    estimateRetrySeconds(attempts),
  );

  useEffect(() => {
    const timer = window.setInterval(() => {
      setRemaining((value) => (value <= 1 ? 0 : value - 1));
    }, 1000);

    return () => window.clearInterval(timer);
  }, []);

  return <span>预计下次重试：{remaining}s</span>;
}