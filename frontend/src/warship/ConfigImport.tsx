/**
 * 配置导入：只读核对旧版 script.cfg 的字段去向（ALAS 卡片版式）。
 */
import { Download, FileJson } from "lucide-react";
import { useWarship } from "./context";
import { Group, Row } from "./ui";

export function ConfigImport() {
  const { setToast, report, setReport, api, job } = useWarship();
  const download = () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: "application/json" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = "舰娘肝帝-字段核对报告.json";
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  return (
    <div className="settings-page warship-settings">
      <h1 className="modern-sr-title">配置导入</h1>
      <Group title="旧配置字段核对">
        <Row label="选择旧配置" help="只读解析 script.cfg，对照已知字段生成去向报告；不启用旧任务，不保存账号、密码或注册码。">
          <label className="button secondary">
            <FileJson size={16} />选择文件
            <input hidden type="file" accept=".cfg,.json" onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) void job("核对旧配置", async () => {
                if (file.size > 2000000) throw new Error("配置文件不能超过 2MB");
                const config = JSON.parse(await file.text());
                setReport(await api("legacy-report", { config }));
                setToast("字段核对完成");
              });
              e.target.value = "";
            }} />
          </label>
        </Row>
        {report && <>
          <Row label="核对结果" help={`已核对 ${report.total_known} 个已知字段，收到 ${report.received} 个配置项。`}>
            <button className="button secondary" onClick={download}><Download size={15} />下载完整报告</button>
          </Row>
          {Object.entries(report.counts as Record<string, number>).map(([key, value]) => <Row key={key} label={key}><strong>{value}</strong></Row>)}
        </>}
      </Group>
    </div>
  );
}
