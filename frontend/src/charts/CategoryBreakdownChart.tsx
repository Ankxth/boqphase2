import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { fmtKg, fmtPct, titleCase } from "../lib/format";

// Data-viz note: fixed 8-hue categorical order from the dataviz skill's
// validated reference palette (dark mode), never reassigned or cycled --
// this is the CVD-safety mechanism, so slot order stays stable across
// re-renders even as category values change. Categories beyond the 8th
// fold into a neutral "Other" bucket rather than reusing a hue.
const CATEGORICAL_DARK = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"];
const OTHER_COLOR = "#6e6c5e";

export interface CategoryDatum {
  category: string;
  gwp_kg_co2e: number;
  pct_of_total: number;
}

export function CategoryBreakdownChart({ categories }: { categories: CategoryDatum[] }) {
  const sorted = [...categories].sort((a, b) => b.gwp_kg_co2e - a.gwp_kg_co2e);
  const top = sorted.slice(0, 8);
  const rest = sorted.slice(8);
  const otherTotal = rest.reduce((s, r) => s + r.gwp_kg_co2e, 0);
  const otherPct = rest.reduce((s, r) => s + r.pct_of_total, 0);

  const data = [
    ...top.map((c, i) => ({ ...c, color: CATEGORICAL_DARK[i] })),
    ...(rest.length ? [{ category: "other", gwp_kg_co2e: otherTotal, pct_of_total: otherPct, color: OTHER_COLOR }] : []),
  ];

  const height = Math.max(220, data.length * 34);

  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 60, left: 4, bottom: 4 }}>
          <XAxis type="number" hide />
          <YAxis
            type="category"
            dataKey="category"
            tickFormatter={(v) => titleCase(v)}
            width={132}
            tick={{ fill: "#a9a797", fontSize: 11.5 }}
            axisLine={false}
            tickLine={false}
          />
          <Tooltip content={<CatTooltip />} cursor={{ fill: "rgba(255,255,255,0.03)" }} />
          <Bar dataKey="gwp_kg_co2e" radius={[0, 4, 4, 0]} barSize={18}>
            {data.map((d, i) => (
              <Cell key={i} fill={d.color} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function CatTooltip({ active, payload }: any) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div className="neu-raised rounded-lg border border-line bg-bg-card px-3 py-2 text-[12px]">
      <div className="font-medium text-ink">{titleCase(d.category)}</div>
      <div className="mt-1 tabular text-ink-soft">
        {fmtKg(d.gwp_kg_co2e)} · {fmtPct(d.pct_of_total)}
      </div>
    </div>
  );
}
