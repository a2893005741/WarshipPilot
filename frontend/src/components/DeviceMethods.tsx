import { Gauge, Link, MousePointerClick, Save, ScanLine } from "lucide-react";
import { useEffect, useState } from "react";

type BenchResult = {
  method: string;
  ok: boolean;
  cost: number | null;
  rating: string;
  error: string;
  detail: any;
};
type BenchRun = {
  time: string;
  results: BenchResult[];
  recommended: string | null;
};
export type DeviceState = {
  screenshot_method: string;
  control_method: string;
  mumu_path: string;
  screenshot_methods: string[];
  control_methods: string[];
  ready: boolean;
  error: string;
  benchmark: {
    running: boolean;
    kind: string;
    progress: string;
    error: string;
    results: { screenshot?: BenchRun; click?: BenchRun };
  };
};

const ms = (s: number | null) =>
  s === null || s === undefined ? "—" : `${(s * 1000).toFixed(1)} ms`;

function ResultTable({
  run,
  kind,
  onUse,
}: {
  run?: BenchRun;
  kind: "screenshot" | "click";
  onUse: (m: string) => void;
}) {
  if (!run) return null;
  return (
    <table className="bench-table">
      <thead>
        <tr>
          <th>方式</th>
          <th>结果</th>
          <th>耗时</th>
          <th>评级</th>
          <th>{kind === "screenshot" ? "画面准确性" : "游戏响应"}</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {run.results.map((r) => (
          <tr key={r.method} className={r.ok ? "ok" : "bad"}>
            <td>
              <code>{r.method}</code>
              {run.recommended === r.method && <b className="tag">推荐</b>}
            </td>
            <td>{r.ok ? "可用" : "不可用"}</td>
            <td>{ms(r.cost)}</td>
            <td>{r.rating || "—"}</td>
            <td>
              {kind === "screenshot"
                ? r.detail?.checks
                  ? `${r.detail.checks - r.detail.differing_checks}/${r.detail.checks} 项一致 · 页面 ${r.detail.page ?? "未识别"}`
                  : r.error
                : r.detail?.clicks
                  ? `${r.detail.reacted}/${r.detail.clicks} 次切换成功`
                  : r.error}
              {r.ok || (!r.detail?.checks && !r.detail?.clicks) ? null : (
                <div className="hint">{r.error}</div>
              )}
            </td>
            <td>
              {r.ok && (
                <button className="button secondary" onClick={() => onUse(r.method)}>
                  使用
                </button>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function DeviceMethods({
  api,
  device,
  serial,
  connectError,
  connected,
  onChanged,
  onError,
}: {
  api: (path: string, body?: any) => Promise<any>;
  device?: DeviceState;
  serial: string;
  connectError: string;
  connected: boolean;
  onChanged: () => void;
  onError: (m: string) => void;
}) {
  const [shot, setShot] = useState("nemu_ipc");
  const [control, setControl] = useState("ADB");
  const [mumu, setMumu] = useState("");
  const [clickReady, setClickReady] = useState(false);
  const [serialInput, setSerialInput] = useState(serial);
  useEffect(() => {
    setSerialInput(serial);
  }, [serial]);
  useEffect(() => {
    if (device) {
      setShot(device.screenshot_method);
      setControl(device.control_method);
      setMumu(device.mumu_path);
    }
  }, [device?.screenshot_method, device?.control_method, device?.mumu_path]);
  if (!device) return null;
  const running = device.benchmark.running;
  const save = (s = shot, c = control) =>
    api("device-config", {
      screenshot_method: s,
      control_method: c,
      mumu_path: mumu,
    })
      .then(onChanged)
      .catch((e) => onError(e.message));
  const bench = (kind: "screenshot" | "click") =>
    api("benchmark", { kind, methods: [] })
      .then(() => {
        setClickReady(false);
        onChanged();
      })
      .catch((e) => onError(e.message));

  return (
    <section className="panel device-methods">
      <div className="panel-heading">
        <div>
          <Gauge size={18} />
          <h2>截图与控制方式</h2>
        </div>
        <span className={device.ready ? "status-ok" : "status-bad"}>
          {device.ready ? "已就绪" : connected ? "未初始化" : "未连接"}
        </span>
      </div>
      <div className="panel-body">
        <div className="method-grid">
          <label className="wide">
            模拟器 Serial（启动时自动连接，只连这个地址；MuMu12
            多开：16384、16416、16448…）
            <div className="serial-row">
              <input
                value={serialInput}
                onChange={(e) => setSerialInput(e.target.value)}
                placeholder="127.0.0.1:16416"
              />
              <button
                className="button primary"
                onClick={() =>
                  api("serial", { serial: serialInput })
                    .then(onChanged)
                    .catch((e) => onError(e.message))
                }
              >
                <Link size={16} />
                保存并连接
              </button>
            </div>
            {connected ? (
              <span className="status-ok">已连接 {serial}</span>
            ) : connectError ? (
              <span className="hint error">{connectError}</span>
            ) : null}
          </label>
        </div>
        <div className="method-grid">
          <label>
            截图方式
            <select
              value={shot}
              onChange={(e) => setShot(e.target.value)}
              disabled={running}
            >
              {device.screenshot_methods.map((m) => (
                <option key={m}>{m}</option>
              ))}
            </select>
          </label>
          <label>
            控制方式
            <select
              value={control}
              onChange={(e) => setControl(e.target.value)}
              disabled={running}
            >
              {device.control_methods.map((m) => (
                <option key={m}>{m}</option>
              ))}
            </select>
          </label>
          <label className="wide">
            MuMu 安装目录（nemu_ipc 用，留空自动查找）
            <input
              value={mumu}
              onChange={(e) => setMumu(e.target.value)}
              placeholder="例如 D:\MuMu\MuMuPlayer"
              disabled={running}
            />
          </label>
        </div>
        <button className="button primary" disabled={running} onClick={() => save()}>
          <Save size={16} />
          保存并重新初始化
        </button>
        {device.error && (
          <p className="hint error">初始化失败：{device.error}</p>
        )}

        <h3>
          <ScanLine size={16} /> 截图测试
        </h3>
        <p className="hint">
          每种方式截图 15 次取最快 80% 的平均值，并与 ADB
          无损截图比对全部页面颜色检查。不会点击游戏。
        </p>
        <button
          className="button secondary"
          disabled={running || !device.ready}
          onClick={() => bench("screenshot")}
        >
          测试全部截图方式
        </button>
        <ResultTable
          run={device.benchmark.results.screenshot}
          kind="screenshot"
          onUse={(m) => {
            setShot(m);
            save(m, control);
          }}
        />

        <h3>
          <MousePointerClick size={16} /> 点击测试
        </h3>
        <p className="hint">
          会在出征页的「远征」和「演习」标签之间来回切换，确认每种方式点击后游戏有反应，最后切回原标签。切换标签不会改变游戏数据。
        </p>
        <label className="check">
          <input
            type="checkbox"
            checked={clickReady}
            onChange={(e) => setClickReady(e.target.checked)}
            disabled={running}
          />
          游戏已停在出征页的远征或演习标签，可以开始点击
        </label>
        <button
          className="button secondary"
          disabled={running || !device.ready || !clickReady}
          onClick={() => bench("click")}
        >
          测试全部控制方式
        </button>
        <ResultTable
          run={device.benchmark.results.click}
          kind="click"
          onUse={(m) => {
            setControl(m);
            save(shot, m);
          }}
        />

        {running && <p className="hint">测试中：{device.benchmark.progress}</p>}
        {device.benchmark.error && (
          <p className="hint error">测试失败：{device.benchmark.error}</p>
        )}
      </div>
    </section>
  );
}
