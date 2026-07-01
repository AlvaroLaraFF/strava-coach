import { useState } from "react";
import { useEvolution } from "../api/hooks";
import { Card, ErrorState, Loading } from "../components/ui";
import { HrTrendChart, PmcChart, PrProgressionChart, VdotThresholdChart } from "../components/charts";

const RANGES = [{ d: 90, l: "90 d" }, { d: 365, l: "1 año" }, { d: 3650, l: "Todo" }];

export default function Evolution() {
  const [days, setDays] = useState(365);
  const { data, isLoading, error } = useEvolution(days);

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
        <h1 className="page-title" style={{ margin: 0 }}>Evolución</h1>
        <div className="seg">
          {RANGES.map((r) => (
            <button key={r.d} className={days === r.d ? "active" : ""} onClick={() => setDays(r.d)}>{r.l}</button>
          ))}
        </div>
      </div>

      {isLoading ? <Loading label="Calculando series…" /> : error ? <ErrorState error={error} /> : (
        <div className="grid" style={{ gap: 16 }}>
          <Card title="Fitness / Fatiga / Forma (CTL · ATL · TSB)">
            <PmcChart data={data!.pmc} />
          </Card>
          <div className="grid cols-2">
            <Card title="VDOT y ritmo umbral">
              <VdotThresholdChart history={data!.snapshot_history} />
            </Card>
            <Card title="Frecuencia cardíaca">
              <HrTrendChart history={data!.snapshot_history} />
            </Card>
          </div>
          <Card title="Progresión de récords (mejor marca acumulada)">
            <PrProgressionChart progression={data!.pr_progression} />
          </Card>
        </div>
      )}
    </div>
  );
}
