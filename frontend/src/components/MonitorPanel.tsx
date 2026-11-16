import { Download, Image, Terminal } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { time, useApp } from "../app/context";
import { SegmentedControl } from "./SegmentedControl";
export function MonitorPanel() {
  const { events, imageUrl, state } = useApp();
  const [view, setView] = useState(
    () => localStorage.getItem("wp-monitor") || "logs",
  );
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    localStorage.setItem("wp-monitor", view);
    if (view === "logs") end.current?.scrollIntoView({ block: "nearest" });
  }, [view, events[0]?.id]);
  return (
    <section className="panel monitor-panel">
      <div className="monitor-tabs">
        <SegmentedControl
          label="监控视图"
          value={view}
          onChange={setView}
          options={[
            {
              value: "logs",
              label: (
                <>
                  <Terminal size={15} />
                  日志
                </>
              ),
            },
            {
              value: "preview",
              label: (
                <>
                  <Image size={15} />
                  截图
                </>
              ),
            },
          ]}
        />
        {view === "preview" && imageUrl && (
          <a
            className="text-button"
            href={imageUrl}
            download="warship-screenshot.png"
          >
            <Download size={14} />
            保存截图
          </a>
        )}
      </div>
      <div className="monitor-view" hidden={view !== "logs"}>
        <div className="wp-log-panel" role="log" aria-label="运行日志">
          {[...events].reverse().map((event) => (
            <div className={`log-line ${event.level}`} key={event.id}>
              <span className="log-ts">{time(event.time)}</span>
              <span className={`log-lvl lvl-${event.level}`}>
                {event.level === "warning" ? "WARN" : "INFO"}
              </span>
              <span className="log-msg">{event.message}</span>
            </div>
          ))}
          {!events.length && <div className="rail-empty">等待运行日志</div>}
          <div ref={end} />
        </div>
      </div>
      <div className="monitor-view" hidden={view !== "preview"}>
        <div className="preview-log">
          {events
            .slice(0, 3)
            .reverse()
            .map((event) => (
              <div className="preview-log-line" key={event.id}>
                <span className="preview-log-ts">{time(event.time)}</span>
                <span className="preview-log-msg">{event.message}</span>
              </div>
            ))}
        </div>
        <div className="preview-stage">
          <div className="preview-screen">
            {imageUrl ? (
              <img src={imageUrl} alt="舰R实时截图" />
            ) : (
              <div className="rail-empty">连接设备后显示实时画面</div>
            )}
          </div>
        </div>
        <div className="wp-frame-caption">
          {state?.frame
            ? `${state.frame.width} × ${state.frame.height} · ${state.device?.screenshot_method} · ${time(state.frame.time)}`
            : "等待截图"}
        </div>
      </div>
    </section>
  );
}
