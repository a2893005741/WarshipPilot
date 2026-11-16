import { Activity, ArrowDownToLine, Camera, Download } from "lucide-react";
import { fullTime, useApp } from "../app/context";
export function ErrorRecords() {
  const { page, events, busy, setToast, api, job, download } = useApp();
  return (
    <div className="warship-utility">
      {page === "records" && (
        <>
          <div className="diagnostic-actions">
            <section className="panel">
              <div className="round-icon">
                <Camera size={22} />
              </div>
              <div>
                <h2>保存当前现场</h2>
                <p>记录截图、实例档案和最近日志，供后续定位。</p>
              </div>
              <button
                className="button secondary"
                disabled={!!busy}
                onClick={() =>
                  job("保存现场", async () => {
                    await api("fault", { reason: "手动保存现场" });
                    setToast("当前现场已保存");
                  })
                }
              >
                保存现场
              </button>
            </section>
            <section className="panel">
              <div className="round-icon">
                <ArrowDownToLine size={22} />
              </div>
              <div>
                <h2>导出诊断资料</h2>
                <p>包含真实游戏截图与样本；分享前先核对账号信息。</p>
              </div>
              <button
                className="button primary"
                disabled={!!busy}
                onClick={() => job("导出诊断包", download)}
              >
                <Download size={16} />
                下载 ZIP
              </button>
            </section>
          </div>
          <section className="panel">
            <div className="panel-heading">
              <div>
                <Activity size={18} />
                <h2>运行时间线</h2>
              </div>
              <span className="tag">最近 120 条</span>
            </div>
            <div className="event-list">
              {events.map((e) => (
                <div className="event" key={e.id}>
                  <time>{fullTime(e.time)}</time>
                  <span className={"event-level " + e.level}>
                    {e.level === "warning" ? "注意" : "记录"}
                  </span>
                  <p>{e.message}</p>
                </div>
              ))}
            </div>
          </section>
        </>
      )}
    </div>
  );
}
