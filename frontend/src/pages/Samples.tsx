import { Camera, Layers, Upload } from "lucide-react";
import { useApp } from "../app/context";
import { SampleCard } from "../components/ui";
export function Samples() {
  const {
    page,
    samples,
    label,
    setSelected,
    replay,
    setReplay,
    replayImage,
    setReplayImage,
    setPage,
    api,
    job,
  } = useApp();
  return (
    <div className="warship-utility">
      {page === "samples" && (
        <>
          <section className="panel replay-panel">
            <div className="panel-heading">
              <div>
                <Upload size={18} />
                <h2>离线截图核对</h2>
              </div>
              <span className="tag">不会控制游戏</span>
            </div>
            <div className="panel-body replay-row">
              <div>
                <p>上传一张 PNG / JPG，与已保存的局部特征比较。</p>
                <small>
                  同尺寸、同坐标比对；相似度 ≥
                  96%，且不同标签没有接近得分时才给出标签。
                </small>
              </div>
              <label className="button secondary">
                <Upload size={16} />
                选择回放图片
                <input
                  hidden
                  type="file"
                  accept="image/png,image/jpeg"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file)
                      void job("核对截图", async () => {
                        if (file.size > 16000000)
                          throw new Error("图片不能大于 16MB");
                        if (replayImage) URL.revokeObjectURL(replayImage);
                        setReplayImage(URL.createObjectURL(file));
                        const r = await api("replay", file, true);
                        setReplay(await r.json());
                      });
                    e.target.value = "";
                  }}
                />
              </label>
            </div>
            {replay && (
              <div className="replay-result">
                <img src={replayImage} alt="离线回放画面" />
                <div>
                  <span className="eyebrow">REPLAY RESULT</span>
                  <h2>{replay.label}</h2>
                  {replay.candidates?.map((c) => (
                    <p key={c.label}>
                      {c.label} <strong>{(c.score * 100).toFixed(1)}%</strong>
                    </p>
                  ))}
                  {!replay.candidates?.length && (
                    <p>还没有可用于此尺寸的局部特征</p>
                  )}
                  <small>这是采集辅助结果，尚未用于任务控制。</small>
                </div>
              </div>
            )}
          </section>
          <div className="section-title">
            <h2>
              已保存的页面 <span>{samples.length}</span>
            </h2>
            <button className="button secondary" onClick={() => setPage("capture")}>
              <Camera size={16} />
              采集新样本
            </button>
          </div>
          <div className="sample-grid">
            {samples.map((sample) => (
              <SampleCard
                key={sample.id}
                sample={sample}
                api={api}
                onClick={() => setSelected(sample)}
              />
            ))}
            {!samples.length && (
              <div className="panel empty-state">
                <Layers size={38} />
                <h3>第一张真实样本，从这里开始</h3>
                <p>到运行总览保存页面，回到这里查看和回放。</p>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
