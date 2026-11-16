import {
  Camera,
  Download,
  FileJson,
  Layers,
  LoaderCircle,
  Radio,
  RefreshCw,
  Save,
  Search,
  SlidersHorizontal,
  Upload,
  X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import "./legacy.css";

export type ColorProfile = {
  base_width: number;
  base_height: number;
  rotation: 0 | 90 | 180 | 270;
  color_order: "RGB" | "BGR";
  tolerance: number;
  mode: "absolute" | "relative";
  anchor_x: number;
  anchor_y: number;
};
type Hint = { index: number; text: string };
type Color = { hex: string; tolerance_hex: string | null };
type Rule = {
  id: string;
  kind: string;
  raw: string;
  context_hints: Hint[];
  point_count: number;
  contains_negative: boolean;
  points?: { x: number; y: number; colors: Color[] }[];
  colors?: Color[];
  issue?: string;
};
type Point = {
  index: number;
  source_x: number;
  source_y: number;
  x: number;
  y: number;
  in_bounds: boolean;
  matched: boolean;
  actual_rgb: string | null;
  expected_rgb: string | null;
  delta?: number[];
  tolerance?: number[];
};
type Evaluation = {
  id: string;
  status: string;
  matched: boolean;
  reason?: string;
  matched_points: number;
  total_points: number;
  outside_points: number;
  match_rate: number;
  mean_delta: number;
  points: Point[];
  width: number;
  height: number;
  profile: ColorProfile;
  context_hints: Hint[];
};
type Scan = {
  candidates: Evaluation[];
  evaluated_rules: number;
  excluded_rules: number;
  fully_matched: number;
  latency_ms: number;
  error?: string;
  frame_id?: number;
  time?: string;
};
export type LegacyState = {
  profile: ColorProfile;
  observing: boolean;
  result: Scan | null;
  stats: Record<string, number>;
};
type Api = (path: string, body?: any, binary?: boolean) => Promise<any>;
type Catalog = {
  source: string;
  source_sha256: string;
  decoded_crc32: string;
  stats: Record<string, number>;
  items: Rule[];
};
type Snapshot = {
  url: string;
  base64: string;
  name: string;
  width: number;
  height: number;
};
const defaultProfile: ColorProfile = {
  base_width: 540,
  base_height: 960,
  rotation: 270,
  color_order: "BGR",
  tolerance: 20,
  mode: "absolute",
  anchor_x: 0,
  anchor_y: 0,
};
const kindNames: Record<string, string> = {
  points: "颜色坐标",
  colors: "颜色组合",
  needs_review: "待核对",
};
const percent = (n: number) => (n * 100).toFixed(0) + "%";
function sameProfile(a: ColorProfile, b: ColorProfile) {
  return (Object.keys(a) as (keyof ColorProfile)[]).every((k) => a[k] === b[k]);
}
async function toSnapshot(blob: Blob, name: string): Promise<Snapshot> {
  if (blob.size > 16_000_000) throw new Error("图片不能大于16MB");
  const url = URL.createObjectURL(blob);
  try {
    const base64 = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result).split(",")[1]);
      reader.onerror = () => reject(new Error("读取图片失败"));
      reader.readAsDataURL(blob);
    });
    const size = await new Promise<{ width: number; height: number }>(
      (resolve, reject) => {
        const image = new Image();
        image.onload = () =>
          resolve({ width: image.naturalWidth, height: image.naturalHeight });
        image.onerror = () => reject(new Error("图片格式无法读取"));
        image.src = url;
      },
    );
    if (Math.max(size.width, size.height) > 8192)
      throw new Error("图片尺寸不能大于8192像素");
    return { url, base64, name, ...size };
  } catch (error) {
    URL.revokeObjectURL(url);
    throw error;
  }
}
function downloadJson(value: any, name: string) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function LegacySummary({
  value,
  onOpen,
}: {
  value: LegacyState;
  onOpen: () => void;
}) {
  const best = value.result?.candidates[0];
  return (
    <section className="panel legacy-summary">
      <div className="panel-heading">
        <div>
          <Layers size={17} />
          <h2>原脚本颜色规则</h2>
        </div>
        <button className="text-button" onClick={onOpen}>
          打开素材与核对 →
        </button>
      </div>
      <div className="legacy-summary-content">
        <div>
          <strong>{value.stats.point_expressions}</strong>
          <small>条原颜色坐标规则 · {value.stats.points} 个点</small>
        </div>
        <div>
          <span>{value.observing ? "实时观察已开启" : "实时观察未开启"}</span>
          <p>
            {value.result?.error ||
              (value.result
                ? `${value.result.fully_matched} 条全部点匹配 · 最相近 ${best?.id || "无"}${best ? " / " + percent(best.match_rate) : ""}`
                : "打开素材页，用当前画面核对或启用观察。")}
          </p>
          <small>
            {value.result?.frame_id
              ? `核对帧 #${value.result.frame_id} · ${value.result.latency_ms} ms · 候选结果`
              : "只比较截图，不触发游戏操作"}
          </small>
        </div>
      </div>
    </section>
  );
}

export default function LegacyRules({
  api,
  live,
  hasFrame,
  backendOnline,
  onSaved,
  onError,
}: {
  api: Api;
  live: LegacyState | undefined;
  hasFrame: boolean;
  backendOnline: boolean;
  onSaved: () => void;
  onError: (message: string) => void;
}) {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState("");
  const [ruleId, setRuleId] = useState("legacy-2120");
  const [detail, setDetail] = useState<Rule | null>(null);
  const [profile, setProfile] = useState<ColorProfile>(
    live?.profile || defaultProfile,
  );
  const [observing, setObserving] = useState(live?.observing || false);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const snapshotRef = useRef<Snapshot | null>(null);
  const [scan, setScan] = useState<Scan | null>(null);
  const [evaluation, setEvaluation] = useState<Evaluation | null>(null);
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [tab, setTab] = useState<"rules" | "identifiers">("rules");
  const [identifiers, setIdentifiers] = useState<
    { constant_index: number; identifier: string; decoded: string }[]
  >([]);
  const [chosenOnly, setChosenOnly] = useState(false);
  const [pointIndex, setPointIndex] = useState<number | null>(null);
  const imageRef = useRef<HTMLDivElement>(null);
  const requestId = useRef(0);
  useEffect(() => {
    let active = true;
    api("legacy-catalog")
      .then((v) => {
        if (active) setCatalog(v);
      })
      .catch((e) => onError(e.message));
    return () => {
      active = false;
    };
  }, []);
  useEffect(() => {
    let active = true;
    setDetail(null);
    setEvaluation(null);
    setPointIndex(null);
    api("legacy-rule?id=" + encodeURIComponent(ruleId))
      .then((v) => {
        if (active) setDetail(v);
      })
      .catch((e) => onError(e.message));
    return () => {
      active = false;
    };
  }, [ruleId]);
  useEffect(() => {
    if (tab === "identifiers" && !identifiers.length)
      api("legacy-identifiers")
        .then(setIdentifiers)
        .catch((e) => onError(e.message));
  }, [tab]);
  useEffect(
    () => () => {
      if (snapshotRef.current) URL.revokeObjectURL(snapshotRef.current.url);
    },
    [],
  );
  const dirty =
    !!live &&
    (!sameProfile(profile, live.profile) || observing !== live.observing);
  function change<K extends keyof ColorProfile>(
    key: K,
    value: ColorProfile[K],
  ) {
    requestId.current++;
    setProfile((p) => ({ ...p, [key]: value }));
    setEvaluation(null);
    setScan(null);
    setMessage("设置已变更，重新核对后结果会更新。");
  }
  async function job(name: string, fn: () => Promise<void>) {
    if (busy) return;
    setBusy(name);
    setMessage("");
    try {
      await fn();
    } catch (e) {
      setMessage((e as Error).message);
    } finally {
      setBusy("");
    }
  }
  function putSnapshot(value: Snapshot) {
    if (snapshotRef.current) URL.revokeObjectURL(snapshotRef.current.url);
    snapshotRef.current = value;
    setSnapshot(value);
    setEvaluation(null);
    setScan(null);
    setPointIndex(null);
  }
  async function check(
    value: Snapshot,
    selected: string | null,
    config = profile,
  ) {
    const id = ++requestId.current;
    const result = await api("legacy-check", {
      profile: config,
      image_base64: value.base64,
      rule_id: selected,
    });
    if (id !== requestId.current) return;
    if (selected) {
      setEvaluation(result);
      setPointIndex(null);
    } else setScan(result);
  }
  async function capture() {
    const response = await api("frame");
    const value = await toSnapshot(
      await response.blob(),
      `实机截图 · 帧 #${response.headers.get("X-Frame-Id")}`,
    );
    putSnapshot(value);
    await check(value, null);
    if (detail?.kind === "points") await check(value, ruleId);
  }
  async function upload(file: File) {
    const value = await toSnapshot(file, file.name);
    putSnapshot(value);
    await check(value, null);
    if (detail?.kind === "points") await check(value, ruleId);
  }
  async function save() {
    const result = await api("legacy-settings", { profile, observing });
    setProfile(result.profile);
    setObserving(result.observing);
    onSaved();
    setMessage("核对设置已保存，下次启动继续使用。");
  }
  async function exportPackage() {
    const response = await api("legacy-download");
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = "舰娘肝帝-原脚本识别素材.zip";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  function anchor(e: React.MouseEvent<HTMLDivElement>) {
    if (profile.mode !== "relative" || !snapshot || !imageRef.current) return;
    const box = imageRef.current.getBoundingClientRect();
    const x = Math.max(
      0,
      Math.min(
        snapshot.width - 1,
        Math.round(((e.clientX - box.left) / box.width) * snapshot.width),
      ),
    );
    const y = Math.max(
      0,
      Math.min(
        snapshot.height - 1,
        Math.round(((e.clientY - box.top) / box.height) * snapshot.height),
      ),
    );
    requestId.current++;
    setProfile((p) => ({ ...p, anchor_x: x, anchor_y: y }));
    setEvaluation(null);
    setScan(null);
  }
  const candidateIds = new Set(scan?.candidates.map((c) => c.id));
  const filtered = (catalog?.items || []).filter(
    (item) =>
      (!kind || item.kind === kind) &&
      (!chosenOnly || !scan || candidateIds.has(item.id)) &&
      (!query ||
        JSON.stringify(item).toLowerCase().includes(query.toLowerCase())),
  );
  const filteredIdentifiers = identifiers.filter(
    (item) =>
      !query ||
      JSON.stringify(item).toLowerCase().includes(query.toLowerCase()),
  );
  return (
    <div className="legacy-workspace">
      <div className="legacy-stats">
        {[
          ["point_expressions", "颜色坐标"],
          ["points", "原颜色点"],
          ["color_groups", "颜色组合"],
          ["decoded_identifiers", "中文标识"],
        ].map(([key, title]) => (
          <div key={key}>
            <strong>{catalog?.stats[key] ?? "—"}</strong>
            <span>{title}</span>
          </div>
        ))}
        <div className="legacy-source">
          <span>舰娘肝帝 6.7.7</span>
          <small>
            核心容器 CRC {catalog?.decoded_crc32 || "…"} · 保留原规则
          </small>
          <button
            className="text-button"
            disabled={!!busy}
            onClick={() => job("导出原素材", exportPackage)}
          >
            <Download size={14} />
            导出完整素材
          </button>
        </div>
      </div>
      <section className="panel legacy-settings">
        <div className="panel-heading">
          <div>
            <SlidersHorizontal size={17} />
            <h2>坐标与颜色核对</h2>
          </div>
          <span className="tag">
            {dirty ? "有未保存设置" : "使用已保存设置"}
          </span>
        </div>
        <div className="panel-body">
          <div className="legacy-profile-fields">
            <label>
              原坐标宽
              <input
                type="number"
                min={16}
                max={8192}
                value={profile.base_width}
                onChange={(e) => change("base_width", Number(e.target.value))}
              />
            </label>
            <label>
              原坐标高
              <input
                type="number"
                min={16}
                max={8192}
                value={profile.base_height}
                onChange={(e) => change("base_height", Number(e.target.value))}
              />
            </label>
            <label>
              顺时针旋转
              <select
                value={profile.rotation}
                onChange={(e) =>
                  change(
                    "rotation",
                    Number(e.target.value) as ColorProfile["rotation"],
                  )
                }
              >
                {[0, 90, 180, 270].map((v) => (
                  <option key={v} value={v}>
                    {v}°
                  </option>
                ))}
              </select>
            </label>
            <label>
              原颜色顺序
              <select
                value={profile.color_order}
                onChange={(e) =>
                  change("color_order", e.target.value as "RGB" | "BGR")
                }
              >
                <option>BGR</option>
                <option>RGB</option>
              </select>
            </label>
            <label>
              额外通道容差
              <input
                type="number"
                min={0}
                max={80}
                value={profile.tolerance}
                onChange={(e) => change("tolerance", Number(e.target.value))}
              />
            </label>
            <label>
              点的坐标方式
              <select
                value={profile.mode}
                onChange={(e) =>
                  change("mode", e.target.value as ColorProfile["mode"])
                }
              >
                <option value="absolute">固定位置</option>
                <option value="relative">相对锚点</option>
              </select>
            </label>
            {profile.mode === "relative" && (
              <>
                <label>
                  画面锚点 X
                  <input
                    type="number"
                    min={0}
                    max={8191}
                    value={profile.anchor_x}
                    onChange={(e) => change("anchor_x", Number(e.target.value))}
                  />
                </label>
                <label>
                  画面锚点 Y
                  <input
                    type="number"
                    min={0}
                    max={8191}
                    value={profile.anchor_y}
                    onChange={(e) => change("anchor_y", Number(e.target.value))}
                  />
                </label>
              </>
            )}
          </div>
          <div className="legacy-settings-bottom">
            <p>
              540×960 / 270° / BGR
              已在先前母港截图上找到全点匹配。原有色差与额外容差取较大值；这些设置用于截图核对。
            </p>
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={observing}
                onChange={(e) => setObserving(e.target.checked)}
              />
              随实时截图观察候选
            </label>
            <button
              className="button primary"
              disabled={!!busy}
              onClick={() => job("保存设置", save)}
            >
              <Save size={15} />
              保存设置
            </button>
          </div>
        </div>
      </section>
      {message && (
        <div className="notice legacy-message">
          <span>{message}</span>
          <button className="icon-button" onClick={() => setMessage("")}>
            <X size={14} />
          </button>
        </div>
      )}
      <div className="legacy-grid">
        <section className="panel legacy-library">
          <div className="legacy-library-tabs">
            <button
              className={tab === "rules" ? "active" : ""}
              onClick={() => setTab("rules")}
            >
              识别规则
            </button>
            <button
              className={tab === "identifiers" ? "active" : ""}
              onClick={() => setTab("identifiers")}
            >
              中文标识
            </button>
          </div>
          <div className="legacy-search">
            <Search size={16} />
            <input
              aria-label="搜索原脚本素材"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="搜索远征、结算、规则编号…"
            />
          </div>
          {tab === "rules" && (
            <div className="legacy-filters">
              <select
                aria-label="素材类型"
                value={kind}
                onChange={(e) => setKind(e.target.value)}
              >
                <option value="">全部规则类型</option>
                <option value="points">颜色坐标</option>
                <option value="colors">颜色组合</option>
                <option value="needs_review">待核对</option>
              </select>
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  disabled={!scan}
                  checked={chosenOnly}
                  onChange={(e) => setChosenOnly(e.target.checked)}
                />
                只看本次候选
              </label>
            </div>
          )}
          <div className="legacy-library-caption">
            {tab === "rules"
              ? `${filtered.length} / ${catalog?.items.length || 0} 条表达式`
              : `${filteredIdentifiers.length} 个中文标识`}
          </div>
          <div className="legacy-rule-list">
            {tab === "rules"
              ? filtered.map((rule) => (
                  <button
                    className={
                      "legacy-rule " + (rule.id === ruleId ? "active" : "")
                    }
                    key={rule.id}
                    onClick={() => {
                      requestId.current++;
                      setRuleId(rule.id);
                      setMessage("");
                    }}
                  >
                    <div>
                      <strong>{rule.id}</strong>
                      <span>
                        {rule.kind === "points"
                          ? `${rule.point_count} 个点`
                          : kindNames[rule.kind]}
                      </span>
                    </div>
                    <p>
                      {rule.context_hints.map((h) => h.text).join(" / ") ||
                        rule.raw}
                    </p>
                    {rule.contains_negative && (
                      <small>含负坐标 · 需要核对锚点</small>
                    )}
                  </button>
                ))
              : filteredIdentifiers.map((identifier) => (
                  <div
                    className="legacy-identifier"
                    key={identifier.constant_index}
                  >
                    <strong>{identifier.decoded}</strong>
                    <code>{identifier.identifier}</code>
                    <small>原常量 #{identifier.constant_index}</small>
                  </div>
                ))}
            {!(tab === "rules"
              ? filtered.length
              : filteredIdentifiers.length) && (
              <div className="empty-state">
                <p>没有符合搜索条件的素材</p>
              </div>
            )}
          </div>
        </section>
        <div className="legacy-main">
          <section className="panel">
            <div className="panel-heading">
              <div>
                <Camera size={17} />
                <h2>在真实画面上核对</h2>
              </div>
              <span className="tag">
                {snapshot
                  ? `${snapshot.width} × ${snapshot.height}`
                  : "等待截图"}
              </span>
            </div>
            <div className="legacy-frame-toolbar">
              <button
                className="button primary"
                disabled={!hasFrame || !!busy || !backendOnline}
                onClick={() => job("取得并核对实机截图", capture)}
              >
                <RefreshCw size={15} />
                取当前画面
              </button>
              <label className={"button secondary " + (busy ? "disabled" : "")}>
                <Upload size={15} />
                选择离线截图
                <input
                  type="file"
                  hidden
                  disabled={!!busy}
                  accept="image/png,image/jpeg"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) void job("核对离线截图", () => upload(file));
                    e.target.value = "";
                  }}
                />
              </label>
              <button
                className="button secondary"
                disabled={!snapshot || !!busy}
                onClick={() =>
                  job("扫描原规则", async () => {
                    await check(snapshot!, null);
                  })
                }
              >
                扫描候选
              </button>
              <small>
                {snapshot?.name || "使用当前画面或离线截图，不改变游戏页面"}
              </small>
            </div>
            {snapshot ? (
              <div
                ref={imageRef}
                className={
                  "legacy-frame " +
                  (profile.mode === "relative" ? "anchor-mode" : "")
                }
                onClick={anchor}
              >
                <img
                  src={snapshot.url}
                  alt="用于原脚本规则核对的截图"
                  draggable={false}
                />
                {evaluation?.points
                  ?.filter((p) => p.in_bounds)
                  .map((p) => (
                    <button
                      key={p.index}
                      title={`点${p.index} (${p.x},${p.y}) ${p.matched ? "匹配" : "不匹配"}`}
                      className={
                        "legacy-point " +
                        (p.matched ? "hit" : "miss") +
                        (pointIndex === p.index ? " selected" : "")
                      }
                      style={{
                        left: ((p.x + 0.5) / snapshot.width) * 100 + "%",
                        top: ((p.y + 0.5) / snapshot.height) * 100 + "%",
                      }}
                      onClick={(e) => {
                        e.stopPropagation();
                        setPointIndex(p.index);
                      }}
                    >
                      {p.index + 1}
                    </button>
                  ))}
                {profile.mode === "relative" && (
                  <div
                    className="legacy-anchor"
                    style={{
                      left: (profile.anchor_x / snapshot.width) * 100 + "%",
                      top: (profile.anchor_y / snapshot.height) * 100 + "%",
                    }}
                  >
                    ＋
                  </div>
                )}
              </div>
            ) : (
              <div className="legacy-frame-empty">
                <Camera size={36} />
                <h3>把旧规则放回真实画面</h3>
                <p>点击“取当前画面”，或选择一张离线截图。</p>
                <small>
                  取到的画面会固定，方便逐点核对；实时采集继续运行。
                </small>
              </div>
            )}
            <div className="legacy-frame-caption">
              <span>绿色：匹配 · 红色：不匹配 · 点击点查看明细</span>
              <span>
                {profile.mode === "relative"
                  ? "点击截图设置锚点"
                  : "整条规则的所有点均通过才算匹配"}
              </span>
            </div>
          </section>
          <section className="panel legacy-detail">
            <div className="panel-heading">
              <div>
                <Layers size={17} />
                <h2>{detail?.id || "加载规则"}</h2>
              </div>
              <button
                className="button primary"
                disabled={!snapshot || detail?.kind !== "points" || !!busy}
                onClick={() =>
                  job("核对此条规则", async () => {
                    await check(snapshot!, ruleId);
                  })
                }
              >
                核对此条
              </button>
            </div>
            {detail && (
              <div className="panel-body">
                <div className="legacy-detail-title">
                  <span className="tag">{kindNames[detail.kind]}</span>
                  <span>原常量 #{detail.id.split("-")[1]}</span>
                  <button
                    className="text-button"
                    onClick={() =>
                      downloadJson(
                        { rule: detail, profile, result: evaluation },
                        detail.id + "-核对.json",
                      )
                    }
                  >
                    <FileJson size={14} />
                    导出本条
                  </button>
                </div>
                {evaluation &&
                  (evaluation.status === "unavailable" ? (
                    <div className="notice">{evaluation.reason}</div>
                  ) : (
                    <div
                      className={
                        "legacy-verdict " +
                        (evaluation.matched ? "matched" : "")
                      }
                    >
                      <div>
                        <strong>
                          {evaluation.matched
                            ? "全部点匹配"
                            : evaluation.outside_points
                              ? "存在越界点"
                              : "部分点不匹配"}
                        </strong>
                        <small>
                          {evaluation.matched_points} /{" "}
                          {evaluation.total_points} 点 · 平均通道差{" "}
                          {evaluation.mean_delta} · {evaluation.outside_points}{" "}
                          点越界
                        </small>
                      </div>
                      <b>{percent(evaluation.match_rate)}</b>
                    </div>
                  ))}
                <p className="legacy-context">
                  附近文字：
                  {detail.context_hints.map((h) => h.text).join(" / ") ||
                    "未提取到相邻短文本"}
                  <small>文字来自相邻常量，规则所属页面尚未确认。</small>
                </p>
                <pre className="legacy-raw">{detail.raw}</pre>
                {detail.issue && (
                  <div className="notice error">{detail.issue}</div>
                )}
                {detail.colors && (
                  <div className="legacy-swatches">
                    {detail.colors.map((c, i) => (
                      <code key={i}>
                        <i
                          style={{
                            background:
                              "#" +
                              (profile.color_order === "BGR"
                                ? c.hex.slice(4) +
                                  c.hex.slice(2, 4) +
                                  c.hex.slice(0, 2)
                                : c.hex),
                          }}
                        />
                        {c.hex}
                        {c.tolerance_hex ? "-" + c.tolerance_hex : ""}
                      </code>
                    ))}
                  </div>
                )}
                {!!evaluation?.points?.length && (
                  <div className="legacy-point-table">
                    <table>
                      <thead>
                        <tr>
                          <th>点</th>
                          <th>原坐标 → 画面</th>
                          <th>期望 RGB</th>
                          <th>实际 RGB</th>
                          <th>结果</th>
                        </tr>
                      </thead>
                      <tbody>
                        {evaluation.points.map((point) => (
                          <tr
                            key={point.index}
                            className={
                              pointIndex === point.index ? "selected" : ""
                            }
                            onClick={() => setPointIndex(point.index)}
                          >
                            <td>{point.index + 1}</td>
                            <td>
                              ({point.source_x},{point.source_y}) → ({point.x},
                              {point.y})
                            </td>
                            <td>
                              <code>{point.expected_rgb || "—"}</code>
                            </td>
                            <td>
                              <code>{point.actual_rgb || "—"}</code>
                            </td>
                            <td>
                              <span
                                className={
                                  point.matched ? "point-pass" : "point-fail"
                                }
                              >
                                {!point.in_bounds
                                  ? "越界"
                                  : point.matched
                                    ? "匹配"
                                    : "不匹配"}
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                {pointIndex !== null && evaluation?.points?.[pointIndex] && (
                  <p className="hint">
                    点 {pointIndex + 1} · RGB 通道差：
                    {evaluation.points[pointIndex].delta?.join(" / ") ||
                      "越界"}{" "}
                    · 允许值：
                    {evaluation.points[pointIndex].tolerance?.join(" / ") ||
                      "—"}
                  </p>
                )}
              </div>
            )}
          </section>
          <section className="panel legacy-candidates">
            <div className="panel-heading">
              <div>
                <Search size={17} />
                <h2>本次画面候选</h2>
              </div>
              <span className="tag">至少 3 点 · 最多 12 条</span>
            </div>
            {scan ? (
              <>
                <div className="legacy-scan-stats">
                  {scan.evaluated_rules} 条参与 · {scan.excluded_rules}{" "}
                  条越界排除 · {scan.fully_matched} 条全点匹配 ·{" "}
                  {scan.latency_ms} ms
                </div>
                <div className="legacy-candidate-list">
                  {scan.candidates.map((candidate) => (
                    <button
                      className={candidate.matched ? "all-hit" : ""}
                      key={candidate.id}
                      disabled={!!busy}
                      onClick={() => {
                        setRuleId(candidate.id);
                        setMessage("已选择候选，点击“核对此条”显示画面叠点。");
                      }}
                    >
                      <div>
                        <strong>{candidate.id}</strong>
                        <span>
                          {candidate.matched
                            ? "全点匹配"
                            : percent(candidate.match_rate)}
                        </span>
                      </div>
                      <p>
                        {candidate.context_hints
                          .map((h) => h.text)
                          .join(" / ") || "没有附近文字"}
                      </p>
                      <small>
                        {candidate.matched_points}/{candidate.total_points} 点 ·
                        平均差 {candidate.mean_delta}
                      </small>
                    </button>
                  ))}
                </div>
                <p className="legacy-candidate-note">
                  这是按当前核对设置得到的颜色候选；不会据此自动判定页面或发送输入。
                </p>
              </>
            ) : (
              <div className="empty-state">
                <p>取得画面后扫描，查看最相近的原规则。</p>
              </div>
            )}
          </section>
          {live?.observing && (
            <section className="panel legacy-live">
              <div className="panel-heading">
                <div>
                  <Radio size={17} />
                  <h2>后台实时观察</h2>
                </div>
                <span className="tag">
                  {backendOnline ? "随截图更新" : "后台离线 · 上次结果"}
                </span>
              </div>
              <div className="panel-body">
                {live.result?.error ? (
                  <p>{live.result.error}</p>
                ) : (
                  <>
                    <p>
                      {live.result?.frame_id
                        ? `帧 #${live.result.frame_id} · ${live.result.time ? new Date(live.result.time).toLocaleTimeString("zh-CN", { hour12: false }) : ""} · ${live.result.fully_matched} 条全点匹配`
                        : "等待下一张实时截图"}
                    </p>
                    <div className="legacy-live-chips">
                      {live.result?.candidates.slice(0, 6).map((c) => (
                        <span key={c.id} className={c.matched ? "matched" : ""}>
                          {c.id} {c.matched_points}/{c.total_points}
                        </span>
                      ))}
                    </div>
                    <small>
                      上方核对画面保持固定，后台观察结果来自实时新帧。
                      {dirty
                        ? "当前表单有未保存设置，后台继续使用已保存设置。"
                        : ""}
                    </small>
                  </>
                )}
              </div>
            </section>
          )}
        </div>
      </div>
      {busy && (
        <div className="legacy-working">
          <LoaderCircle size={17} className="spin" />
          {busy}
        </div>
      )}
    </div>
  );
}
