import { CalendarClock, ChevronRight, Pause, Play, Square } from "lucide-react";
import { useEffect, useState } from "react";
import { useApp } from "../app/context";
export function ModernRail() {
  const { state, schema, api, busy, taskControl, setPage, page } = useApp(),
    job = state?.automation;
  const [tasks, setTasks] = useState<Record<string, any>>({});
  useEffect(() => {
    let active = true;
    const refresh = () =>
      void api("task-configs")
        .then((r) => {
          if (active) setTasks(r.tasks);
        })
        .catch(() => {});
    refresh();
    window.addEventListener("wp-config-saved", refresh);
    return () => {
      active = false;
      window.removeEventListener("wp-config-saved", refresh);
    };
  }, [page, job?.enabled, JSON.stringify(job?.due)]);
  const queue = Object.entries(tasks)
    .filter(([id, t]) => schema?.tasks[id]?.executable && t.enabled)
    .map(([id, t]) => ({
      id,
      ...t,
      next: job?.due?.[id],
      status:
        job?.running && job.task === id
          ? "running"
          : job?.due?.[id] && new Date(job.due[id]).getTime() > Date.now()
            ? "waiting"
            : "pending",
    }))
    .sort((a, b) =>
      a.status === "running"
        ? -1
        : b.status === "running"
          ? 1
          : a.priority - b.priority,
    );
  const count = (status: string) =>
    queue.filter((t) => t.status === status).length;
  const labels: Record<string, string> = {
    running: "运行中",
    pending: "待运行",
    waiting: "等待中",
  };
  return (
    <div className="instance-page-rail">
      <section className="scheduler-widget" aria-label="调度器">
        <div className="scheduler-widget-heading">
          <div>
            <CalendarClock size={18} />
            <span>调度器</span>
          </div>
        </div>
        <div className="scheduler-stats">
          {["running", "pending", "waiting"].map((status) => (
            <div className={status} key={status}>
              <strong>{count(status)}</strong>
              <span>{labels[status]}</span>
            </div>
          ))}
        </div>
        <button
          className={`button scheduler-toggle ${job?.scheduler ? "danger" : "primary"}`}
          disabled={!!busy}
          onClick={() =>
            taskControl(job?.scheduler ? "scheduler-stop" : "scheduler-start")
          }
        >
          {job?.scheduler ? (
            <Square size={11} fill="currentColor" />
          ) : (
            <Play size={14} />
          )}{" "}
          {job?.scheduler ? "停止调度器" : "启动调度器"}
        </button>
        {job?.scheduler && !state?.serial && (
          <p className="wp-rail-hint">等待连接 {state?.last_serial}</p>
        )}
        {job?.running && (
          <div className="wp-run-controls">
            <button
              className="button secondary"
              disabled={!!busy}
              onClick={() =>
                taskControl(job.status === "paused" ? "resume" : "pause")
              }
            >
              {job.status === "paused" ? (
                <Play size={14} />
              ) : (
                <Pause size={14} />
              )}{" "}
              {job.status === "paused" ? "恢复" : "暂停"}
            </button>
            <button
              className="button secondary"
              onClick={() => taskControl("stop")}
            >
              停止当前任务
            </button>
          </div>
        )}
      </section>
      <section className="rail-schedule" aria-label="任务计划">
        <div className="rail-task-list">
          <div className="rail-task-heading">
            <strong>任务计划</strong>
            <span>{queue.length}</span>
          </div>
          <section className="rail-queue-group tasks">
            <div className="rail-queue-body">
              {queue.map((t) => (
                <a
                  key={t.id}
                  className={`rail-task-item ${t.status}`}
                  href={`#/i/warship/task/${t.id}`}
                  onClick={(e) => {
                    e.preventDefault();
                    setPage(t.id);
                  }}
                >
                  <div className="rail-task-main">
                    <strong>{schema?.tasks[t.id]?.name}</strong>
                    <small>
                      {t.next
                        ? new Date(t.next).toLocaleString("zh-CN", {
                            hour12: false,
                          })
                        : "按计划时间运行"}
                    </small>
                  </div>
                  <span className={`rail-task-state ${t.status}`}>
                    {t.status === "running" && (
                      <span className="thinking-dots">
                        <i />
                        <i />
                        <i />
                      </span>
                    )}
                    <span className="state-label">{labels[t.status]}</span>
                  </span>
                  <ChevronRight size={13} />
                </a>
              ))}
            </div>
          </section>
          {!queue.length && <div className="rail-empty">没有启用的任务</div>}
        </div>
      </section>
      {job?.error && <p className="error-message">{job.error}</p>}
    </div>
  );
}
