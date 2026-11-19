/**
 * 设备页：ADB 实例发现与连接、当前实例档案、截图与控制方式（ALAS 设置页版式）。
 */
import { ArrowRight, Link, RefreshCw, Unplug } from "lucide-react";
import { Input } from "../components/ui/input";
import { useWarship } from "./context";
import DeviceMethods from "./DeviceMethods";
import { Group, Row } from "./ui";

export function Devices() {
  const { state, setState, devices, setDevices, adbPath, setAdbPath, address, setAddress, busy, setToast,
    setPage, api, job, discover, control } = useWarship();
  const profile = state?.profile;
  return (
    <div className="settings-page warship-settings">
      <h1 className="modern-sr-title">设备</h1>
      <Group title="安卓实例" action={
        <button className="button primary" disabled={!!busy} onClick={discover}><RefreshCw size={16} />发现设备</button>}>
        <Row label="ADB 程序路径" help="留空时自动查找随包 ADB 或 MuMu ADB。">
          <Input value={adbPath} onChange={(e) => setAdbPath(e.target.value)} placeholder="自动查找" />
        </Row>
        <Row label="连接 ADB 地址" help="MuMu12 多开端口：16384、16416、16448…；连接后点「发现设备」。">
          <div className="warship-inline">
            <Input aria-label="ADB 地址" value={address} onChange={(e) => setAddress(e.target.value)} placeholder="127.0.0.1:16416" />
            <button className="button secondary" disabled={!!busy} onClick={() => job("连接 ADB", async () => {
              const result = await api("connect-adb", { serial: address });
              setToast(result.message);
              setDevices(await api("devices", {}));
            })}><Link size={16} />连接</button>
          </div>
        </Row>
        <Row label="ADB 服务" help="重新连接已保存的模拟器。重启共享服务会短暂断开同一服务上的设备。">
          <button className="button secondary" disabled={!!busy || !state?.last_serial || !!state.automation?.running || !!state.device?.benchmark.running} onClick={() => job("重启 ADB", async () => {
            const result = await api("restart-adb", {});
            setToast(result.message);
            setDevices(await api("devices", {}));
            setState(await api("state"));
          })}><RefreshCw size={16} />重启并重连</button>
        </Row>
        {devices.map((device) => (
          <Row key={device.serial} label={device.game_installed ? "战舰少女R" : "其他安卓实例"}
            help={`${device.serial} · ${device.state} · ${device.size || device.detail}${device.error ? " · " + device.error : ""}`}>
            <button className={"button " + (device.game_installed ? "primary" : "secondary")}
              disabled={!device.game_installed || device.state !== "device" || !!busy}
              onClick={() => job("连接舰R", async () => {
                await api("select", { serial: device.serial });
                setState(await api("state"));
                setPage("overview");
                setToast("已连接舰R，正在取得画面");
              })}>{device.game_installed ? "连接" : "不适用"}<ArrowRight size={14} /></button>
          </Row>
        ))}
        {!devices.length && <p className="warship-empty">点击「发现设备」读取 ADB 已连接的安卓实例；只能连接安装了战舰少女R的实例。</p>}
      </Group>

      <Group title="当前实例档案" action={profile && (
        <button className="button secondary" disabled={!!busy} onClick={() => control("disconnect")}><Unplug size={16} />断开设备</button>)}>
        {profile ? <>
          <Row label="设备地址"><code>{state?.serial}</code></Row>
          <Row label="游戏包名"><code>{profile.package}</code></Row>
          <Row label="游戏版本">{profile.version}</Row>
          <Row label="实际截图">{state?.frame ? `${state.frame.width} × ${state.frame.height}` : "等待取得"}</Row>
          <Row label="安卓报告尺寸">{profile.android_size}</Row>
          <Row label="连接时的前台">{profile.game_foreground ? "战舰少女R" : "其他页面"}</Row>
          <Row label="连接时的旧脚本">{profile.legacy_running ? "仍在运行" : "未发现运行进程"}</Row>
        </> : <p className="warship-empty">连接后读取设备与游戏档案；连接后可执行远征、战役、演习、任务奖励与原脚本出征。</p>}
      </Group>

      <DeviceMethods api={api} device={state?.device} serial={state?.last_serial || ""}
        connectError={state?.connect_error || ""} connected={!!state?.serial}
        onChanged={() => void api("state").then(setState)} onError={setToast} />
    </div>
  );
}
