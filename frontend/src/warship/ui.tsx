import React, { useEffect, useState } from "react";
import type { Sample } from "./context";
import { fullTime } from "./context";
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
    <button className="warship-sample" onClick={onClick}>
      <div className="warship-thumb">
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

/** ALAS 设置页的卡片：组指示条 + 标题，右侧可放操作按钮。 */
export function Group({ title, action, children }: { title: string; action?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="panel config-group">
      <div className="panel-heading">
        <div><span className="group-indicator" /><h2>{title}</h2></div>
        {action}
      </div>
      {children}
    </section>
  );
}

/** ALAS 字段行：左侧名称与说明，右侧控件。 */
export function Row({ label, help, children }: { label: string; help?: string; children: React.ReactNode }) {
  return (
    <div className="field-row">
      <div className="field-label"><label>{label}</label>{help && <p>{help}</p>}</div>
      <div className="field-control">{children}</div>
    </div>
  );
}
