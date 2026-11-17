/**
 * 采集：实时画面、锁定后框选稳定特征并保存页面样本、连续画面留档（ALAS 卡片版式）。
 */
import { ArrowRight, Camera, Lock, Monitor, Pause, Play, RefreshCw, Square } from "lucide-react";
import { Select } from "../components/FormControls";
import { Input } from "../components/ui/input";
import { statusName, time, useWarship } from "./context";
import { Group, Row } from "./ui";

export function Capture() {
  const { state, setState, samples, busy, imageUrl, shownFrame, label, setLabel, note, setNote, roi, setRoi, setDragEnd,
    setPage, api, job, control, beginRoi, endRoi, saveSample, isLive, hasDevice, bounds, previewRef, drag, point } = useWarship();
  const paused = state?.status === "paused";
  return (
    <div className="settings-page warship-settings">
      <h1 className="modern-sr-title">采集</h1>
      <Group title="实时画面" action={
        <div className="warship-inline">
          <button className="button secondary" disabled={!hasDevice || !!busy} onClick={() => control(isLive ? "pause" : "resume")}>
            {isLive ? <Pause size={15} /> : <Play size={15} />}{isLive ? "锁定画面" : "恢复实时"}
          </button>
          <button className="button secondary" disabled={!isLive || !!busy} onClick={() => control("refresh")} title="刷新画面"><RefreshCw size={15} /></button>
        </div>}>
        <div className={"warship-preview " + (paused ? "croppable" : "")} onPointerDown={beginRoi}
          onPointerMove={(e) => { if (drag.current) setDragEnd(point(e)); }} onPointerUp={endRoi}
          onPointerCancel={() => { drag.current = null; setDragEnd(null); }}>
          {imageUrl ? <>
            <img ref={previewRef} src={imageUrl} draggable={false} alt="MuMu 舰R真实画面" />
            {bounds && <div className="warship-roi" style={bounds}><span>识别特征</span></div>}
            {paused && <div className="warship-badge"><Lock size={12} /> 已锁定 · 拖动框选稳定区域</div>}
          </> : <div className="warship-preview-empty">
            <Monitor size={42} strokeWidth={1} />
            <p>连接舰R实例后在这里查看真实画面</p>
            <button className="button primary" onClick={() => setPage("devices")}>连接设备<ArrowRight size={16} /></button>
          </div>}
        </div>
        <p className="warship-empty">
          {shownFrame ? `帧 ${String(shownFrame.id).padStart(5, "0")} · ${time(shownFrame.time)} · ${shownFrame.width} × ${shownFrame.height} · 上帧 ${shownFrame.latency_ms} ms` : "尚无截图"}
          {" · "}{statusName[state?.status || "idle"] ?? ""}
        </p>
      </Group>

      <Group title="标注当前页面">
        <Row label="页面类型">
          <Select value={label} onChange={(e) => setLabel(e.target.value)}>
            {(state?.labels || ["母港"]).map((l) => <option key={l}>{l}</option>)}
          </Select>
        </Row>
        <Row label="稳定识别特征" help={roi ? `区域：${roi.join(" / ")} px` : "先锁定画面，再拖动框选固定的标题或按钮，避开资源数字、立绘和动画；不框选则保存整页样本。"}>
          {roi && <button className="button secondary" onClick={() => setRoi(null)}>清除框选</button>}
        </Row>
        <Row label="备注" help="可选。">
          <Input value={note} maxLength={400} onChange={(e) => setNote(e.target.value)} placeholder="例如：普通母港，无弹窗" />
        </Row>
        <Row label="采集辅助识别" help={state?.recognition.score != null
          ? `区域相似度 ${(state.recognition.score * 100).toFixed(1)}%${state.recognition.conflict ? " · 多标签冲突" : ""}`
          : "保存局部特征后开始比对。"}>
          <strong>{state?.recognition.label || "未分类"}</strong>
        </Row>
        <Row label="保存" help={`已保存 ${samples.length} 个样本，${new Set(samples.map((s) => s.label)).size} 种页面。`}>
          <button className="button primary" disabled={!shownFrame || !!busy} onClick={() => job("保存样本", saveSample)}><Camera size={16} />保存页面样本</button>
        </Row>
      </Group>

      <Group title="连续画面留档">
        <Row label={state?.session ? "正在记录游戏画面变化" : "保留游戏过程供故障核对"}
          help={`每 5 秒最多保存一帧，跳过相同截图；每批最多 600 张。${state?.session ? ` 本批已保存 ${state.session_count} 张。` : ""}`}>
          <button className={"button " + (state?.session ? "secondary" : "primary")} disabled={!isLive || !!busy}
            onClick={() => job("切换留档", async () => {
              await api(state?.session ? "session-stop" : "session-start", {});
              setState(await api("state"));
            })}>
            {state?.session ? <Square size={15} /> : <Play size={15} />}{state?.session ? "结束留档" : "开始留档"}
          </button>
        </Row>
      </Group>
    </div>
  );
}
