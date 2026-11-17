/**
 * 样本：离线截图核对与已保存页面样本（ALAS 卡片版式），点击样本查看大图或删除。
 */
import { Camera, Trash2, Upload } from "lucide-react";
import { Modal } from "../components/ui";
import { fullTime, useWarship } from "./context";
import { Group, Row, SampleCard } from "./ui";

export function Samples() {
  const { samples, setSamples, selected, setSelected, sampleImage, replay, setReplay, replayImage, setReplayImage, setPage,
    api, job, setToast } = useWarship();
  return (
    <div className="settings-page warship-settings">
      <h1 className="modern-sr-title">样本</h1>
      <Group title="离线截图核对" action={<span className="warship-status">不会控制游戏</span>}>
        <Row label="上传截图" help="PNG / JPG，与已保存的局部特征同尺寸、同坐标比对；相似度 ≥ 96% 且不同标签没有接近得分时才给出标签。">
          <label className="button secondary">
            <Upload size={16} />选择图片
            <input hidden type="file" accept="image/png,image/jpeg" onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) void job("核对截图", async () => {
                if (file.size > 16000000) throw new Error("图片不能大于 16MB");
                if (replayImage) URL.revokeObjectURL(replayImage);
                setReplayImage(URL.createObjectURL(file));
                const r = await api("replay", file, true);
                setReplay(await r.json());
              });
              e.target.value = "";
            }} />
          </label>
        </Row>
        {replay && <div className="warship-replay">
          <img src={replayImage} alt="离线回放画面" />
          <div>
            <h3>{replay.label}</h3>
            {replay.candidates?.map((c) => <p key={c.label}>{c.label} <strong>{(c.score * 100).toFixed(1)}%</strong></p>)}
            {!replay.candidates?.length && <p>还没有可用于此尺寸的局部特征</p>}
            <p className="warship-muted">采集辅助结果，不用于任务控制。</p>
          </div>
        </div>}
      </Group>

      <Group title={`已保存的页面（${samples.length}）`} action={
        <button className="button secondary" onClick={() => setPage("capture")}><Camera size={16} />采集新样本</button>}>
        {samples.length ? <div className="warship-samples">
          {samples.map((sample) => <SampleCard key={sample.id} sample={sample} api={api} onClick={() => setSelected(sample)} />)}
        </div> : <p className="warship-empty">还没有样本。到「采集」锁定画面后保存页面，回到这里查看和回放。</p>}
      </Group>

      {selected && <Modal title={`${selected.label}${selected.roi ? " · 含局部特征" : " · 整页样本"}`} onClose={() => setSelected(null)}>
        <div className="warship-sample-detail">
          {sampleImage && <img src={sampleImage} alt={selected.label} />}
          <p>{selected.note || "无备注"}</p>
          <p className="warship-muted">{fullTime(selected.time)} · {selected.frame.width} × {selected.frame.height}{selected.roi ? ` · 区域 ${selected.roi.join(" / ")}` : ""}</p>
          <button className="button secondary" onClick={() => job("删除样本", async () => {
            await api("sample-delete", { id: selected.id });
            setSamples(await api("samples"));
            setSelected(null);
            setToast("样本已删除");
          })}><Trash2 size={15} />删除样本</button>
        </div>
      </Modal>}
    </div>
  );
}
