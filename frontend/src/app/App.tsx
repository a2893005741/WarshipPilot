import {
  Anchor,
  Bug,
  ChevronRight,
  Download,
  Home,
  Menu,
  Moon,
  Power,
  Settings2,
  Sun,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { AppFeedback } from "../components/AppFeedback";
import { TaskNavTree } from "../components/TaskNavTree";
import { Capture } from "../pages/Capture";
import { ConfigImport } from "../pages/ConfigImport";
import { Devices } from "../pages/Devices";
import { ErrorRecords } from "../pages/ErrorRecords";
import { LegacyRulesPage } from "../pages/LegacyRulesPage";
import { Login } from "../pages/Login";
import { Overview } from "../pages/Overview";
import { Samples } from "../pages/Samples";
import { TaskConfig } from "../pages/TaskConfig";
import { Updater } from "../pages/Updater";
import { useApp } from "./context";

const labels: Record<string, string> = {
  overview: "总览",
  devices: "设备设置",
  update: "软件更新",
  records: "故障记录",
  capture: "画面采集",
  samples: "页面样本",
  legacy: "原脚本素材",
  tasks: "配置导入",
};
export function App() {
  const { page, setPage, state, schema, authed, connected, setConfirm } =
    useApp();
  const [mobile, setMobile] = useState(false),
    [dark, setDark] = useState(
      () => localStorage.getItem("wp-dark") === "true",
    );
  useEffect(() => {
    document.documentElement.dataset.theme = dark
      ? "modern-dark"
      : "modern-light";
    localStorage.setItem("wp-dark", String(dark));
  }, [dark]);
  useEffect(() => setMobile(false), [page]);
  if (!authed) return <Login />;
  const task = schema?.tasks[page],
    title = task?.name || labels[page] || "总览";
  const nav = (id: string, Icon: typeof Home) => (
    <a
      href={`#/i/warship/${id}`}
      className={page === id ? "active" : ""}
      onClick={(e) => {
        e.preventDefault();
        setPage(id);
      }}
    >
      <Icon size={17} />
      {labels[id]}
    </a>
  );
  return (
    <>
      <div
        className={`app-shell modern-shell ${task ? "task-config-shell" : ""} ${mobile ? "mobile-open" : ""}`}
      >
        <header className="topbar">
          <div className="sidebar-brand modern-topbar-brand">
            <a
              className="sidebar-brand-left wp-brand"
              href="#/i/warship/overview"
              onClick={(e) => {
                e.preventDefault();
                setPage("overview");
              }}
            >
              <Anchor size={27} />
              <strong>WarshipPilot</strong>
            </a>
          </div>
          <button
            className="icon-button mobile-toggle"
            aria-label="展开导航"
            onClick={() => setMobile(!mobile)}
          >
            <Menu size={20} />
          </button>
          <span className="modern-topbar-title">{title}</span>
          <div className="topbar-actions wp-topbar-actions">
            <span className={`status ${connected ? "running" : "error"}`}>
              <i />
              {connected ? "已连接" : "正在重连"}
            </span>
            <button
              className="icon-button"
              aria-label={dark ? "切换浅色主题" : "切换深色主题"}
              onClick={() => setDark(!dark)}
            >
              {dark ? <Sun size={18} /> : <Moon size={18} />}
            </button>
            <button
              className="icon-button"
              aria-label="退出后台"
              onClick={() => setConfirm("shutdown")}
            >
              <Power size={18} />
            </button>
          </div>
        </header>
        {mobile && (
          <button
            className="sidebar-backdrop"
            aria-label="关闭导航"
            onClick={() => setMobile(false)}
          />
        )}
        <aside className="sidebar">
          <div className="wp-mobile-brand">
            <Anchor size={24} />
            WarshipPilot
            <button
              className="icon-button"
              aria-label="关闭导航"
              onClick={() => setMobile(false)}
            >
              <X size={18} />
            </button>
          </div>
          <nav className="primary-nav" aria-label="主导航">
            {nav("overview", Home)}
            {nav("records", Bug)}
            {nav("update", Download)}
            {nav("devices", Settings2)}
          </nav>
          <TaskNavTree />
          <div className="sidebar-footer wp-sidebar-footer">
            <span>
              舰R · {state?.serial || state?.last_serial || "未配置设备"}
            </span>
            <small>v{state?.version}</small>
          </div>
        </aside>
        <div className="main-shell">
          <div className="modern-page-nav">
            <div className="breadcrumb">
              <a
                href="#/i/warship/overview"
                onClick={(e) => {
                  e.preventDefault();
                  setPage("overview");
                }}
              >
                <Home size={15} />
                <span>主页</span>
              </a>
              <div className="instance-tabs">
                <a
                  href="#/i/warship/overview"
                  className="instance-tab active"
                  onClick={(e) => {
                    e.preventDefault();
                    setPage("overview");
                  }}
                >
                  <i
                    className={`tiny-dot ${state?.status === "live" ? "teal" : ""}`}
                  />
                  舰R
                </a>
              </div>
              {task && (
                <>
                  <ChevronRight size={13} />
                  <select
                    className="wp-task-switcher"
                    aria-label="切换任务"
                    value={page}
                    onChange={(e) => setPage(e.target.value)}
                  >
                    {Object.entries(schema!.tasks).map(([id, t]) => (
                      <option key={id} value={id}>
                        {t.name}
                      </option>
                    ))}
                  </select>
                </>
              )}
              <span className="wp-instance-address">
                {state?.serial || state?.last_serial}
              </span>
            </div>
          </div>
          {!connected && (
            <div className="connection-banner" role="status">
              后台连接已断开，正在自动重连。
            </div>
          )}
          <main id="main-content" tabIndex={-1}>
            {task ? (
              <TaskConfig key={page} task={page} />
            ) : page === "capture" ? (
              <Capture />
            ) : page === "samples" ? (
              <Samples />
            ) : page === "devices" ? (
              <Devices />
            ) : page === "update" ? (
              <Updater />
            ) : page === "records" ? (
              <ErrorRecords />
            ) : page === "tasks" ? (
              <ConfigImport />
            ) : page === "legacy" ? (
              <LegacyRulesPage />
            ) : (
              <Overview />
            )}
          </main>
        </div>
      </div>
      <AppFeedback />
    </>
  );
}
