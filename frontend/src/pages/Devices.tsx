import {
  ArrowRight,
  Link,
  Monitor,
  Plug,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { useApp } from "../app/context";
import DeviceMethods from "../components/DeviceMethods";
export function Devices() {
  const {
    page,
    state,
    setState,
    devices,
    setDevices,
    adbPath,
    setAdbPath,
    address,
    setAddress,
    busy,
    setToast,
    label,
    setPage,
    api,
    job,
    discover,
    control,
  } = useApp();
  return (
    <div className="warship-utility">
      {page === "devices" && (
        <div className="devices-layout">
          <section className="panel">
            <div className="panel-heading">
              <div>
                <Monitor size={18} />
                <h2>安卓实例</h2>
              </div>
              <button className="button primary" disabled={!!busy} onClick={discover}>
                <RefreshCw size={16} />
                发现设备
              </button>
            </div>
            <div className="panel-body">
              <label>
                ADB 程序路径
                <input
                  value={adbPath}
                  onChange={(e) => setAdbPath(e.target.value)}
                  placeholder="留空时自动查找随包 ADB 或 MuMu ADB"
                />
              </label>
              <p className="hint">
                仅允许连接安装了战舰少女R的实例；其他游戏实例会列出供区分。
              </p>
              <div className="device-list">
                {devices.map((device) => (
                  <div
                    className={
                      "device-card " +
                      (device.game_installed ? "compatible" : "")
                    }
                    key={device.serial}
                  >
                    <div className="device-symbol">
                      <Monitor size={24} />
                    </div>
                    <div>
                      <strong>
                        {device.game_installed ? "战舰少女R" : "其他安卓实例"}
                      </strong>
                      <code>{device.serial}</code>
                      <small>
                        {device.state} · {device.size || device.detail}
                      </small>
                      {device.error && <small>{device.error}</small>}
                    </div>
                    <button
                      className={
                        device.game_installed ? "primary" : "secondary"
                      }
                      disabled={
                        !device.game_installed ||
                        device.state !== "device" ||
                        !!busy
                      }
                      onClick={() =>
                        job("连接舰R", async () => {
                          await api("select", { serial: device.serial });
                          setState(await api("state"));
                          setPage("overview");
                          setToast("已连接舰R，正在取得画面");
                        })
                      }
                    >
                      {device.game_installed ? "连接" : "不适用"}
                      <ArrowRight size={14} />
                    </button>
                  </div>
                ))}
                {!devices.length && (
                  <div className="empty-state">
                    <Plug size={34} />
                    <h3>发现运行中的实例</h3>
                    <p>点击“发现设备”，读取 ADB 已连接的安卓实例。</p>
                  </div>
                )}
              </div>
              <div className="connect-row">
                <input
                  aria-label="MuMu ADB 地址"
                  value={address}
                  onChange={(e) => setAddress(e.target.value)}
                  placeholder="127.0.0.1:16416"
                />
                <button
                  className="button secondary"
                  disabled={!!busy}
                  onClick={() =>
                    job("连接 ADB", async () => {
                      const result = await api("connect-adb", {
                        serial: address,
                      });
                      setToast(result.message);
                      setDevices(await api("devices", {}));
                    })
                  }
                >
                  <Link size={16} />
                  连接此地址
                </button>
              </div>
            </div>
          </section>
          <section className="panel device-profile">
            <div className="panel-heading">
              <div>
                <ShieldCheck size={18} />
                <h2>当前实例档案</h2>
              </div>
            </div>
            <div className="panel-body">
              {state?.profile ? (
                <>
                  <dl>
                    <dt>设备地址</dt>
                    <dd>{state.serial}</dd>
                    <dt>游戏包名</dt>
                    <dd>{state.profile.package}</dd>
                    <dt>游戏版本</dt>
                    <dd>{state.profile.version}</dd>
                    <dt>实际截图</dt>
                    <dd>
                      {state.frame
                        ? `${state.frame.width} × ${state.frame.height}`
                        : "等待取得"}
                    </dd>
                    <dt>安卓报告尺寸</dt>
                    <dd>{state.profile.android_size}</dd>
                    <dt>连接时的前台</dt>
                    <dd>
                      {state.profile.game_foreground ? "战舰少女R" : "其他页面"}
                    </dd>
                    <dt>连接时的旧脚本</dt>
                    <dd>
                      {state.profile.legacy_running
                        ? "仍在运行"
                        : "未发现运行进程"}
                    </dd>
                  </dl>
                  <button
                    className="button secondary full"
                    disabled={!!busy}
                    onClick={() => control("disconnect")}
                  >
                    断开设备
                  </button>
                </>
              ) : (
                <div className="empty-state">
                  <p>连接后读取设备与游戏档案。</p>
                </div>
              )}
              <p className="hint">连接后可执行原生远征与原脚本出征任务。</p>
            </div>
          </section>
          <DeviceMethods
            api={api}
            device={state?.device}
            serial={state?.last_serial || ""}
            connectError={state?.connect_error || ""}
            connected={!!state?.serial}
            onChanged={() => void api("state").then(setState)}
            onError={setToast}
          />
        </div>
      )}
    </div>
  );
}
