import { Download, FileJson } from "lucide-react";
import { useApp } from "../app/context";
export function ConfigImport() {
  const { key, page, setToast, label, report, setReport, api, job } = useApp();
  return (
    <div className="warship-utility">
      {page === "tasks" && (
        <>
          <section className="panel import-panel">
            <div>
              <h2>旧配置字段核对</h2>
              <p>
                只读解析 script.cfg，对照 518
                个字段生成去向报告。本版不启用旧任务，不保存账号、密码或注册码。
              </p>
            </div>
            <label className="button secondary">
              <FileJson size={17} />
              选择旧配置
              <input
                hidden
                type="file"
                accept=".cfg,.json"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file)
                    void job("核对旧配置", async () => {
                      if (file.size > 2000000)
                        throw new Error("配置文件不能超过 2MB");
                      const config = JSON.parse(await file.text());
                      setReport(await api("legacy-report", { config }));
                      setToast("字段核对完成");
                    });
                  e.target.value = "";
                }}
              />
            </label>
            {report && (
              <div className="import-result">
                <p>
                  已核对 {report.total_known} 个已知字段，收到 {report.received}{" "}
                  个配置项。
                </p>
                <div>
                  {Object.entries(report.counts).map(([key, value]) => (
                    <span key={key}>
                      {key}
                      <b>{String(value)}</b>
                    </span>
                  ))}
                </div>
                <button
                  className="text-button"
                  onClick={() => {
                    const url = URL.createObjectURL(
                      new Blob([JSON.stringify(report, null, 2)], {
                        type: "application/json",
                      }),
                    );
                    const a = document.createElement("a");
                    a.href = url;
                    a.download = "舰娘肝帝-字段核对报告.json";
                    a.click();
                    setTimeout(() => URL.revokeObjectURL(url), 1000);
                  }}
                >
                  <Download size={15} />
                  下载完整报告
                </button>
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}
