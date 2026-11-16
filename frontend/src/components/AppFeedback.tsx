import { Camera, Check, Download, LoaderCircle, Trash2, X } from "lucide-react";
import { fullTime, useApp } from "../app/context";
export function AppFeedback() {
  const {
    setSamples,
    busy,
    toast,
    setToast,
    selected,
    setSelected,
    sampleImage,
    confirm,
    setConfirm,
    api,
    job,
  } = useApp();
  return (
    <div className="warship-utility">
      {" "}
      {busy && (
        <div className="busy">
          <LoaderCircle size={16} className="spin" />
          {busy}
        </div>
      )}
      {toast && (
        <div className="toast">
          <Check size={17} />
          {toast}
          <button onClick={() => setToast("")}>
            <X size={16} />
          </button>
        </div>
      )}
      {selected && (
        <div className="modal-backdrop" onClick={() => setSelected(null)}>
          <section className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="panel-heading">
              <div>
                <Camera size={18} />
                <h2>{selected.label}</h2>
              </div>
              <button className="icon-button" onClick={() => setSelected(null)}>
                <X size={19} />
              </button>
            </div>
            <img
              className="sample-large"
              src={sampleImage}
              alt={selected.label}
            />
            <div className="panel-body">
              <p>{selected.note || "未填写备注"}</p>
              <small>
                {fullTime(selected.time)} · {selected.frame.width} ×{" "}
                {selected.frame.height} ·{" "}
                {selected.roi
                  ? "局部特征 " + selected.roi.join(" / ")
                  : "整页样本，无识别特征"}
              </small>
              <div className="modal-actions">
                <a
                  className="button secondary"
                  href={sampleImage}
                  download={`${selected.label}.png`}
                >
                  <Download size={16} />
                  下载原图
                </a>
                <button
                  className="button danger"
                  disabled={!!busy}
                  onClick={() => setConfirm("delete")}
                >
                  <Trash2 size={15} />
                  删除样本
                </button>
              </div>
            </div>
          </section>
        </div>
      )}
      {confirm && (
        <div className="modal-backdrop confirm">
          <section className="confirm-card">
            <h2>
              {confirm === "shutdown"
                ? "退出舰R助手后台？"
                : "删除这个页面样本？"}
            </h2>
            <p>
              {confirm === "shutdown"
                ? "结束画面采集并退出本软件。再次双击 WarshipPilot.bat 可重新启动。"
                : "原图与局部识别特征会一并删除。"}
            </p>
            <div className="modal-actions">
              <button className="button secondary" onClick={() => setConfirm("")}>
                取消
              </button>
              <button
                className="button danger"
                onClick={() => {
                  const action = confirm;
                  setConfirm("");
                  void job("正在处理", async () => {
                    if (action === "shutdown") {
                      await api("shutdown", {});
                      setToast("后台已退出");
                    } else if (selected) {
                      await api("sample-delete", { id: selected.id });
                      setSelected(null);
                      setSamples(await api("samples"));
                      setToast("样本已删除");
                    }
                  });
                }}
              >
                确认{confirm === "shutdown" ? "退出" : "删除"}
              </button>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
