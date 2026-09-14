import type { FixPosition, Layer } from "../lib/types";

interface Props {
  layers: Layer[];
  fixes: FixPosition[];
  onChange: (fixes: FixPosition[]) => void;
  disabled?: boolean;
}

export function FixPanel({ layers, fixes, onChange, disabled }: Props) {
  const posOf = new Map(fixes.map((f) => [f.layer_id, f.position]));

  function setFix(layerId: number, raw: string) {
    const value = raw.trim() === "" ? null : Number(raw);
    const next = fixes.filter((f) => f.layer_id !== layerId);
    if (value != null && Number.isInteger(value) && value >= 1) {
      next.push({ layer_id: layerId, position: value });
    }
    onChange(next.sort((a, b) => a.position - b.position));
  }

  return (
    <div>
      <div className="row" style={{ alignItems: "flex-start" }}>
        <table style={{ maxWidth: 520 }}>
          <thead>
            <tr>
              <th>图层</th>
              <th>固定在序列第几位（从 1 起，留空不固定）</th>
            </tr>
          </thead>
          <tbody>
            {layers.map((l) => (
              <tr key={l.id}>
                <td>#{l.id}</td>
                <td>
                  <input
                    className="fix-input"
                    type="number"
                    min={1}
                    max={layers.length}
                    disabled={disabled}
                    value={posOf.has(l.id) ? String(posOf.get(l.id)) : ""}
                    onChange={(e) => setFix(l.id, e.target.value)}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="tag" style={{ maxWidth: 360 }}>
          固定某图层在完整刮印序列中的位置后重新计算。若与前驱偏序或湿碰湿链
          冲突，将返回冲突类型与涉及图层。
        </div>
      </div>
    </div>
  );
}
