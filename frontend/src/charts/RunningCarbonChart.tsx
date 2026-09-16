import { Area, AreaChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { fmtDate, fmtKg, fmtNum } from "../lib/format";
import type { DashboardPoint } from "../lib/types";

// Data-viz note: this chart carries exactly one hued series -- the real
// billed-to-date carbon line, in the app's coral accent. The baseline and
// projected-total reference lines are deliberately NEUTRAL (no second
// saturated hue) and always directly labeled, rather than color-coding a
// second series -- coral+amber and coral+moss both failed the dataviz
// skill's own CVD/normal-vision adjacency checks on this dark surface, so
// identity here rides on position + text label, never on a second hue.

interface Props {
  points: DashboardPoint[];
  baselineTotal: number;
  projectedTotal: number | null;
}

export function RunningCarbonChart({ points, baselineTotal, projectedTotal }: Props) {
  const data = points.map((p) => ({
    period: p.period,
    date: p.billed_date,
    kg: p.total_gwp_kg_co2e_to_date,
  }));

  const maxVal = Math.max(baselineTotal, projectedTotal ?? 0, ...data.map((d) => d.kg), 1);

  return (
    <div className="h-72 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 18, right: 16, left: 4, bottom: 4 }}>
          <defs>
            <linearGradient id="coralFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#ff6a3d" stopOpacity={0.32} />
              <stop offset="100%" stopColor="#ff6a3d" stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="rgba(243,241,231,0.07)" vertical={false} />
          <XAxis
            dataKey="period"
            tick={{ fill: "#a9a797", fontSize: 11, fontFamily: "JetBrains Mono, monospace" }}
            axisLine={{ stroke: "rgba(243,241,231,0.14)" }}
            tickLine={false}
          />
          <YAxis
            tick={{ fill: "#a9a797", fontSize: 11, fontFamily: "JetBrains Mono, monospace" }}
            axisLine={false}
            tickLine={false}
            width={54}
            domain={[0, Math.ceil(maxVal * 1.12)]}
            tickFormatter={(v) => fmtNum(v / 1000, 0) + "t"}
          />
          <Tooltip content={<ChartTooltip />} />
          <ReferenceLine
            y={baselineTotal}
            stroke="#a9a797"
            strokeDasharray="4 4"
            strokeWidth={1.5}
            label={{ value: "baseline", position: "insideTopRight", fill: "#a9a797", fontSize: 10.5, fontFamily: "JetBrains Mono, monospace" }}
          />
          {projectedTotal != null && (
            <ReferenceLine
              y={projectedTotal}
              stroke="#e8a94b"
              strokeDasharray="2 3"
              strokeWidth={1.5}
              label={{ value: "projected", position: "insideBottomRight", fill: "#e8a94b", fontSize: 10.5, fontFamily: "JetBrains Mono, monospace" }}
            />
          )}
          <Area
            type="monotone"
            dataKey="kg"
            stroke="#ff6a3d"
            strokeWidth={2.5}
            fill="url(#coralFill)"
            dot={{ r: 4, fill: "#0b0c09", stroke: "#ff6a3d", strokeWidth: 2 }}
            activeDot={{ r: 5.5 }}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

function ChartTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div className="neu-raised rounded-lg border border-line bg-bg-card px-3 py-2 text-[12px]">
      <div className="font-mono text-[10px] uppercase tracking-wide text-ink-faint">{label}</div>
      <div className="mt-0.5 text-ink">{fmtDate(p.date)}</div>
      <div className="mt-1 font-medium text-coral tabular">{fmtKg(p.kg)}</div>
    </div>
  );
}
