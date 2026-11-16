import {
  Activity,
  ArrowRight,
  Camera,
  Crop,
  FolderOpen,
  Image as ImageIcon,
  Layers,
  Lock,
  Monitor,
  Pause,
  Play,
  RefreshCw,
  Square,
} from "lucide-react";
import { statusName, time, useApp } from "../app/context";
import { Metric } from "../components/ui";
export function Capture() {
  const {
    page,
    state,
    setState,
    events,
    samples,
    busy,
    imageUrl,
    shownFrame,
    label,
    setLabel,
    note,
    setNote,
    roi,
    setRoi,
    setDragEnd,
    setPage,
    api,
    job,
    control,
    beginRoi,
    endRoi,
    saveSample,
    isLive,
    hasDevice,
    bounds,
    previewRef,
    drag,
    point,
  } = useApp();
  return (
    <div className="warship-utility">
      {page === "capture" && (
        <>
          <div className="metrics">
            <Metric
              label="游戏实例"
              value={state?.serial || "未连接"}
              detail={state?.profile?.model || "选择安装了舰R的 MuMu"}
              icon={<Monitor />}
            />
            <Metric
              label="实际截图"
              value={
                shownFrame
                  ? `${shownFrame.width} × ${shownFrame.height}`
                  : "等待画面"
              }
              detail={shownFrame ? "截图方向以实际帧为准" : "取得截图后显示"}
              icon={<ImageIcon />}
            />
            <Metric
              label="采集状态"
              value={statusName[state?.status || "idle"]}
              detail={
                shownFrame
                  ? `上帧耗时 ${shownFrame.latency_ms} ms`
                  : "默认每 3 秒取一帧"
              }
              icon={<Activity />}
            />
            <Metric
              label="页面样本"
              value={String(samples.length).padStart(2, "0")}
              detail={`${new Set(samples.map((s) => s.label)).size} 种页面已留档`}
              icon={<Layers />}
            />
          </div>
          <div className="work-grid">
            <section className="panel preview-panel">
              <div className="panel-heading">
                <div>
                  <span className={"live-dot " + (isLive ? "on" : "")} />
                  <h2>游戏实时画面</h2>
                </div>
                <div className="toolbar">
                  <button
                    disabled={!hasDevice || !!busy}
                    onClick={() => control(isLive ? "pause" : "resume")}
                  >
                    {isLive ? <Pause size={15} /> : <Play size={15} />}{" "}
                    {isLive ? "锁定画面" : "恢复实时"}
                  </button>
                  <button
                    className="icon-button"
                    disabled={!isLive || !!busy}
                    onClick={() => control("refresh")}
                    title="刷新画面"
                  >
                    <RefreshCw size={16} />
                  </button>
                </div>
              </div>
              <div
                className={
                  "preview " + (state?.status === "paused" ? "croppable" : "")
                }
                onPointerDown={beginRoi}
                onPointerMove={(e) => {
                  if (drag.current) setDragEnd(point(e));
                }}
                onPointerUp={endRoi}
                onPointerCancel={() => {
                  drag.current = null;
                  setDragEnd(null);
                }}
              >
                {imageUrl ? (
                  <>
                    <img
                      ref={previewRef}
                      src={imageUrl}
                      draggable={false}
                      alt="MuMu 舰R真实画面"
                    />
                    {bounds && (
                      <div className="roi" style={bounds}>
                        <span>识别特征</span>
                      </div>
                    )}
                    {state?.status === "paused" && (
                      <div className="frozen-badge">
                        <Lock size={12} /> 已锁定 · 拖动框选稳定区域
                      </div>
                    )}
                  </>
                ) : (
                  <div className="empty-preview">
                    <Monitor size={46} strokeWidth={1} />
                    <h3>等待连接舰R实例</h3>
                    <p>连接后在这里查看 MuMu 的真实画面</p>
                    <button
                      className="button primary"
                      onClick={() => setPage("devices")}
                    >
                      连接设备 <ArrowRight size={16} />
                    </button>
                  </div>
                )}
              </div>
              <div className="frame-footer">
                <span>
                  {shownFrame ? (
                    <>
                      FRAME {String(shownFrame.id).padStart(5, "0")}
                      <b>·</b>
                      {time(shownFrame.time)}
                      <b>·</b>PNG / ADB
                    </>
                  ) : (
                    "尚无截图"
                  )}
                </span>
                <span>
                  {isLive
                    ? "实时预览"
                    : state?.status === "paused"
                      ? "固定帧"
                      : "未采集"}
                </span>
              </div>
            </section>
            <section className="panel annotation">
              <div className="panel-heading">
                <div>
                  <Crop size={17} />
                  <h2>标注当前页面</h2>
                </div>
                <span className="step">01 → 02</span>
              </div>
              <div className="panel-body">
                <label>
                  页面类型
                  <select
                    value={label}
                    onChange={(e) => setLabel(e.target.value)}
                  >
                    {(state?.labels || ["母港"]).map((l) => (
                      <option key={l}>{l}</option>
                    ))}
                  </select>
                </label>
                <div className="feature-box">
                  <div>
                    <Crop size={17} />
                    <strong>稳定识别特征</strong>
                  </div>
                  <p>
                    {roi
                      ? `区域：${roi.join(" / ")} px`
                      : "先锁定画面，再拖动框选固定的标题或按钮。避开资源数字、角色立绘和动画。"}
                  </p>
                  {roi ? (
                    <button className="text-button" onClick={() => setRoi(null)}>
                      清除框选
                    </button>
                  ) : (
                    <small>不框选也可以保存整页样本</small>
                  )}
                </div>
                <label>
                  备注 <span>可选</span>
                  <textarea
                    value={note}
                    maxLength={400}
                    onChange={(e) => setNote(e.target.value)}
                    placeholder="例如：普通母港，无弹窗"
                    rows={2}
                  />
                </label>
                <button
                  className="button primary full"
                  disabled={!shownFrame || !!busy}
                  onClick={() => job("保存样本", saveSample)}
                >
                  <Camera size={17} />
                  保存页面样本
                </button>
                <div className="recognition">
                  <span>采集辅助识别</span>
                  <strong>{state?.recognition.label || "未分类"}</strong>
                  <small>
                    {state?.recognition.score != null
                      ? `区域相似度 ${(state.recognition.score * 100).toFixed(1)}%${state.recognition.conflict ? " · 多标签冲突" : ""}`
                      : "保存局部特征后开始比对"}
                  </small>
                </div>
              </div>
            </section>
          </div>

          <div className="bottom-grid">
            <section className="panel">
              <div className="panel-heading">
                <div>
                  <FolderOpen size={17} />
                  <h2>连续画面留档</h2>
                </div>
                <span className="tag">PNG + 时间戳</span>
              </div>
              <div className="session-content">
                <div>
                  <p>
                    {state?.session
                      ? "正在记录游戏画面变化"
                      : "可选：保留游戏过程供故障核对"}
                  </p>
                  <small>
                    每 5 秒最多保存一帧，跳过完全相同的截图；每批最多 600
                    张。自行在游戏中操作即可。
                  </small>
                  {state?.session && (
                    <span className="session-count">
                      本批已保存 {state.session_count} 张
                    </span>
                  )}
                </div>
                <button
                  className={state?.session ? "secondary" : "primary"}
                  disabled={!isLive || !!busy}
                  onClick={() =>
                    job("切换留档", async () => {
                      await api(
                        state?.session ? "session-stop" : "session-start",
                        {},
                      );
                      setState(await api("state"));
                    })
                  }
                >
                  {state?.session ? <Square size={15} /> : <Play size={15} />}{" "}
                  {state?.session ? "结束留档" : "开始留档"}
                </button>
              </div>
            </section>
            <section className="panel">
              <div className="panel-heading">
                <div>
                  <Activity size={17} />
                  <h2>最近动态</h2>
                </div>
                <button className="text-button" onClick={() => setPage("records")}>
                  全部记录 <ArrowRight size={14} />
                </button>
              </div>
              <div className="mini-events">
                {events.slice(0, 3).map((e) => (
                  <div key={e.id}>
                    <i className={e.level} />
                    <span>{e.message}</span>
                    <time>{time(e.time)}</time>
                  </div>
                ))}
                {!events.length && <p className="muted">等待后台记录</p>}
              </div>
            </section>
          </div>
        </>
      )}
    </div>
  );
}
