import { CloudDownload, RefreshCw } from "lucide-react";

export type UpdateState = {
  version: string;
  branch: string;
  auto_check: boolean;
  state: string;
  progress: string;
  error: string;
  checked: string;
  latest: null | {
    tag: string;
    version: string;
    current: string;
    notes: string;
    commits: { sha: string; date: string; subject: string }[];
  };
};
const label: Record<string, string> = {
  idle: "未检查",
  checking: "检查中",
  current: "已是最新提交",
  available: "有新提交",
  waiting: "等待任务结束",
  restarting: "正在更新并重启",
  error: "更新失败",
};
export default function UpdatePanel({
  api,
  update,
  onChanged,
  onError,
}: {
  api: (path: string, body?: any) => Promise<any>;
  update?: UpdateState | null;
  onChanged: () => void;
  onError: (m: string) => void;
}) {
  if (!update) return null;
  const working = ["checking", "waiting", "restarting"].includes(update.state);
  const run = (path: string, body: any = {}) =>
    api(path, body)
      .then(onChanged)
      .catch((e) => onError(e.message));
  return (
    <section className="panel update-panel">
      <div className="panel-heading">
        <div>
          <CloudDownload size={18} />
          <h2>软件更新</h2>
        </div>
        <span>
          {label[update.state] || update.state}
          {update.progress ? ` · ${update.progress}` : ""}
        </span>
      </div>
      <div className="panel-body">
        <p>
          当前版本 <b>v{update.version}</b> · 分支 <b>{update.branch}</b>
          {update.latest && (
            <>
              {" "}
              · 本地 {update.latest.current.slice(0, 10)} · 远端{" "}
              {update.latest.tag}
            </>
          )}
        </p>
        {update.latest?.notes && (
          <pre className="release-notes">{update.latest.notes}</pre>
        )}
        <div className="update-actions">
          <button
            className="button secondary"
            disabled={working}
            onClick={() => run("update-check")}
          >
            <RefreshCw size={16} />
            检查更新
          </button>
          <button
            className="button primary"
            disabled={working || update.state !== "available"}
            onClick={() => run("update-install")}
          >
            <CloudDownload size={16} />
            更新并重启
          </button>
        </div>
        <p className="hint">
          更新会等待当前任务结束，再自动重启。调度器开关和下次运行时间会保留。
        </p>
        {update.error && <p className="hint error">{update.error}</p>}
        <label className="check">
          <input
            type="checkbox"
            checked={update.auto_check}
            disabled={working}
            onChange={(e) =>
              run("update-settings", { auto_check: e.target.checked })
            }
          />
          启动后及每 6 小时自动检查
        </label>
      </div>
    </section>
  );
}
