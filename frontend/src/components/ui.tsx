import React, { useEffect, useState } from "react";
import type { Sample } from "../app/context";
import { fullTime } from "../app/context";
export function Metric({
  label,
  value,
  detail,
  icon,
}: {
  label: string;
  value: string;
  detail: string;
  icon: React.ReactNode;
}) {
  return (
    <div className="metric">
      <div>
        <span>{label}</span>
        <div className="metric-icon">{icon}</div>
      </div>
      <strong>{value}</strong>
      <small>{detail}</small>
    </div>
  );
}
export function SampleCard({
  sample,
  api,
  onClick,
}: {
  sample: Sample;
  api: any;
  onClick: () => void;
}) {
  const [url, setUrl] = useState("");
  useEffect(() => {
    let active = true;
    let current = "";
    void api("sample-image?id=" + sample.id)
      .then(async (r: Response) => {
        current = URL.createObjectURL(await r.blob());
        if (active) setUrl(current);
      })
      .catch(() => {});
    return () => {
      active = false;
      if (current) URL.revokeObjectURL(current);
    };
  }, [sample.id]);
  return (
    <button className="sample-card" onClick={onClick}>
      <div className="sample-thumbnail">
        {url && <img src={url} alt={sample.label} loading="lazy" />}
      </div>
      <div>
        <h3>
          {sample.label}
          <span>{sample.roi ? "含局部特征" : "整页样本"}</span>
        </h3>
        <p>{sample.note || `${sample.frame.width} × ${sample.frame.height}`}</p>
        <small>{fullTime(sample.time)}</small>
      </div>
    </button>
  );
}
