import { ArrowRight, Waves } from "lucide-react";
import { useApp } from "../app/context";
export function Login() {
  const { key, setKey, keyInput, setKeyInput, label } = useApp();
  return (
    <div className="warship-utility">
      <div className="login">
        <div className="login-card">
          <div className="brand-mark">
            <Waves />
          </div>
          <p className="eyebrow">WARSHIP PILOT</p>
          <h1>连接你的舰R控制台</h1>
          <p>
            双击运行电脑上的 WarshipPilot.bat
            会自动打开控制台。通过局域网访问时，填写该电脑的访问码。
          </p>
          <label>
            控制台访问码
            <input
              type="password"
              value={keyInput}
              onChange={(e) => setKeyInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") setKey(keyInput.trim());
              }}
              placeholder="来自 config / deploy.yaml"
            />
          </label>
          <button
            className="button primary"
            onClick={() => {
              if (key === keyInput.trim()) location.reload();
              else setKey(keyInput.trim());
            }}
          >
            连接控制台 <ArrowRight size={17} />
          </button>
          <small>
            访问码位于启动电脑 config/deploy.yaml 的
            WebUI.AccessCode，不是游戏账号密码。
          </small>
        </div>
      </div>
    </div>
  );
}
