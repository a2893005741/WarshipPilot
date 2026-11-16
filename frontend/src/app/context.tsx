import React, {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { ApiClient } from "../api/client";
import type { Schema } from "../api/types";
import type { DeviceState } from "../components/DeviceMethods";
import type { LegacyState } from "../components/LegacyRules";
import type { UpdateState } from "../components/UpdaterPanel";
export type Frame = {
  id: number;
  time: string;
  width: number;
  height: number;
  latency_ms: number;
  serial: string;
};
export type Sample = {
  id: string;
  time: string;
  label: string;
  note: string;
  roi: number[] | null;
  frame: Frame;
};
type Recognition = {
  label: string;
  score: number | null;
  conflict?: boolean;
  candidates?: { label: string; score: number }[];
};
type State = {
  automation?: any;
  version: string;
  status: string;
  error: string;
  serial: string;
  last_serial: string;
  adb_path: string;
  frame: Frame | null;
  profile: any;
  recognition: Recognition;
  session: any;
  session_count: number;
  labels: string[];
  samples_count: number;
  legacy?: LegacyState;
  device?: DeviceState;
  update?: UpdateState | null;
  connect_error?: string;
};
type Event = { id: number; time: string; level: string; message: string };
type Device = {
  serial: string;
  state: string;
  game_installed: boolean;
  size?: string;
  detail: string;
  error?: string;
};
export const time = (date: string) =>
  new Date(date).toLocaleTimeString("zh-CN", { hour12: false });
export const fullTime = (date: string) =>
  new Date(date).toLocaleString("zh-CN", { hour12: false });
export const statusName: Record<string, string> = {
  idle: "等待连接",
  live: "正在采集",
  paused: "画面已锁定",
  fault: "采集中断",
};

function readPage() {
  const path = location.hash.slice(1);
  return path.includes("/task/")
    ? decodeURIComponent(path.split("/task/")[1])
    : path.split("/").filter(Boolean).at(-1) || "overview";
}
function useAppData() {
  const [key, setKey] = useState(() => {
    const hash = new URLSearchParams(location.hash.slice(1));
    const k = hash.get("key") || localStorage.getItem("wp-key") || "";
    if (hash.has("key")) history.replaceState(null, "", location.pathname);
    return k;
  });
  const [keyInput, setKeyInput] = useState(key);
  const [authed, setAuthed] = useState(false);
  const [page, setPageState] = useState(readPage);
  const [state, setState] = useState<State | null>(null);
  const [events, setEvents] = useState<Event[]>([]);
  const [devices, setDevices] = useState<Device[]>([]);
  const [samples, setSamples] = useState<Sample[]>([]);
  const [adbPath, setAdbPath] = useState("");
  const [address, setAddress] = useState("127.0.0.1:16416");
  const [busy, setBusy] = useState("");
  const [toast, setToast] = useState("");
  const [connected, setConnected] = useState(false);
  const [imageUrl, setImageUrl] = useState("");
  const [shownFrame, setShownFrame] = useState<Frame | null>(null);
  const [label, setLabel] = useState("母港");
  const [note, setNote] = useState("");
  const [roi, setRoi] = useState<number[] | null>(null);
  const [selected, setSelected] = useState<Sample | null>(null);
  const [sampleImage, setSampleImage] = useState("");
  const [replay, setReplay] = useState<Recognition | null>(null);
  const [replayImage, setReplayImage] = useState("");
  const [report, setReport] = useState<any>(null);
  const [confirm, setConfirm] = useState("");
  const frameRef = useRef<Frame | null>(null);
  const imageRef = useRef("");
  const previewRef = useRef<HTMLImageElement>(null);
  const drag = useRef<number[] | null>(null);
  const [dragEnd, setDragEnd] = useState<number[] | null>(null);
  const keyRef = useRef(key);
  keyRef.current = key;
  const rpcRef = useRef<ApiClient | null>(null);
  const [schema, setSchema] = useState<Schema | null>(null);
  function setPage(value: string) {
    setPageState(value);
    location.hash = Object.keys(schema?.tasks || {}).includes(value)
      ? `/i/warship/task/${value}`
      : `/i/warship/${value}`;
  }
  useEffect(() => {
    const update = () => setPageState(readPage());
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, []);
  useEffect(() => {
    if (authed)
      void api("schema")
        .then(setSchema)
        .catch((e) => setToast(e.message));
  }, [authed, connected]);
  async function api(path: string, body?: any, binary = false): Promise<any> {
    if (
      rpcRef.current?.ready &&
      !binary &&
      ![
        "frame",
        "sample-image",
        "diagnostic",
        "legacy-download",
        "legacy-identifiers",
      ].some((v) => path.startsWith(v))
    ) {
      const [action, query] = path.split("?");
      return rpcRef.current.request(
        action,
        body ?? Object.fromEntries(new URLSearchParams(query)),
      );
    }
    const response = await fetch("/api/" + path, {
      method: body === undefined ? "GET" : "POST",
      headers: {
        Authorization: "Bearer " + keyRef.current,
        ...(binary ? {} : { "Content-Type": "application/json" }),
      },
      body:
        body === undefined ? undefined : binary ? body : JSON.stringify(body),
    });
    if (!response.ok) {
      let error;
      try {
        error = await response.json();
      } catch {
        error = { error: "服务连接失败" };
      }
      if (response.status === 401) setAuthed(false);
      throw new Error(error.error || "请求失败");
    }
    if (
      binary ||
      ["frame", "sample-image", "diagnostic", "legacy-download"].some((v) =>
        path.startsWith(v),
      )
    )
      return response;
    return response.json();
  }
  async function job(name: string, fn: () => Promise<any>) {
    if (busy) return;
    setBusy(name);
    try {
      await fn();
    } catch (error) {
      setToast(String((error as Error).message));
    } finally {
      setBusy("");
    }
  }
  useEffect(() => {
    if (toast) {
      const timer = setTimeout(() => setToast(""), 6000);
      return () => clearTimeout(timer);
    }
  }, [toast]);
  useEffect(() => {
    if (!key) return;
    localStorage.setItem("wp-key", key);
    let stopped = false;
    let socket: ApiClient | undefined;
    let timer: number;
    let lastPush = 0;
    async function connect() {
      try {
        const initial = await api("state");
        if (stopped) return;
        setState(initial);
        setAuthed(true);
        setConnected(true);
        setAdbPath(initial.adb_path);
        setSamples(await api("samples"));
        socket = new ApiClient(
          key,
          (value) => {
            lastPush = Date.now();
            setState(value.state);
            setEvents(value.events);
            setConnected(true);
          },
          () => {
            setConnected(false);
            if (!stopped) timer = window.setTimeout(connect, 3000);
          },
        );
        rpcRef.current = socket;
      } catch (e) {
        setConnected(false);
        if (!stopped) timer = window.setTimeout(connect, 5000);
      }
    }
    let polling = false;
    const poll = window.setInterval(async () => {
      if (stopped || polling || Date.now() - lastPush < 5000) return;
      polling = true;
      try {
        const [value, logs] = await Promise.all([api("state"), api("events")]);
        if (!stopped) {
          setState(value);
          setEvents(logs);
          setConnected(true);
        }
      } catch {
        if (!stopped) setConnected(false);
      } finally {
        polling = false;
      }
    }, 2500);
    void connect();
    return () => {
      stopped = true;
      clearTimeout(timer);
      clearInterval(poll);
      socket?.close();
    };
  }, [key]);
  useEffect(() => {
    const frame = state?.frame;
    if (!frame) {
      setImageUrl("");
      setShownFrame(null);
      frameRef.current = null;
      return;
    }
    if (
      frameRef.current?.id === frame.id &&
      frameRef.current?.serial === frame.serial
    )
      return;
    let cancelled = false;
    (async () => {
      try {
        const response = await api("frame");
        const id = Number(response.headers.get("X-Frame-Id"));
        const blob = await response.blob();
        if (cancelled) return;
        if (id !== frame.id) return;
        const url = URL.createObjectURL(blob);
        if (imageRef.current) URL.revokeObjectURL(imageRef.current);
        imageRef.current = url;
        setImageUrl(url);
        frameRef.current = frame;
        setShownFrame(frame);
        setRoi(null);
      } catch {}
    })();
    return () => {
      cancelled = true;
    };
  }, [state?.frame?.id, state?.serial]);
  useEffect(() => {
    if (!authed) return;
    void api("samples")
      .then(setSamples)
      .catch(() => {});
  }, [state?.samples_count, authed]);
  useEffect(() => {
    if (!selected) {
      setSampleImage("");
      return;
    }
    let active = true;
    let url = "";
    void api("sample-image?id=" + selected.id)
      .then(async (r) => {
        url = URL.createObjectURL(await r.blob());
        if (active) setSampleImage(url);
      })
      .catch((e) => setToast(e.message));
    return () => {
      active = false;
      if (url) URL.revokeObjectURL(url);
    };
  }, [selected]);
  const discover = () =>
    job("正在发现设备", async () => {
      setDevices(await api("devices", { adb_path: adbPath }));
      setToast("设备发现完成");
    });
  const control = (action: string) =>
    job("正在处理", async () => {
      await api("control", { action });
      setState(await api("state"));
    });
  const taskControl = (action: string, task = "") =>
    job("正在处理任务", async () => {
      await api("task-control", { action, task });
      setState(await api("state"));
    });
  const download = async () => {
    const response = await api("diagnostic");
    const url = URL.createObjectURL(await response.blob());
    const a = document.createElement("a");
    a.href = url;
    a.download = "舰R助手-诊断资料.zip";
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  function point(e: React.PointerEvent) {
    const box = previewRef.current!.getBoundingClientRect();
    return [
      Math.max(0, Math.min(1, (e.clientX - box.left) / box.width)),
      Math.max(0, Math.min(1, (e.clientY - box.top) / box.height)),
    ];
  }
  function beginRoi(e: React.PointerEvent) {
    if (state?.status !== "paused" || !shownFrame) return;
    drag.current = point(e);
    setDragEnd(drag.current);
    e.currentTarget.setPointerCapture(e.pointerId);
  }
  function endRoi(e: React.PointerEvent) {
    if (!drag.current || !shownFrame) return;
    const end = point(e);
    const start = drag.current;
    setRoi([
      Math.round(Math.min(start[0], end[0]) * shownFrame.width),
      Math.round(Math.min(start[1], end[1]) * shownFrame.height),
      Math.round(Math.abs(end[0] - start[0]) * shownFrame.width),
      Math.round(Math.abs(end[1] - start[1]) * shownFrame.height),
    ]);
    drag.current = null;
    setDragEnd(null);
  }
  async function saveSample() {
    if (!shownFrame) return;
    await api("sample", { label, note, roi, frame_id: shownFrame.id });
    setSamples(await api("samples"));
    setState(await api("state"));
    setToast("已保存「" + label + "」页面样本");
    setNote("");
  }
  const isLive = state?.status === "live";
  const hasDevice = !!state?.serial;
  const bounds =
    roi && shownFrame
      ? {
          left: (roi[0] / shownFrame.width) * 100 + "%",
          top: (roi[1] / shownFrame.height) * 100 + "%",
          width: (roi[2] / shownFrame.width) * 100 + "%",
          height: (roi[3] / shownFrame.height) * 100 + "%",
        }
      : drag.current && dragEnd
        ? {
            left: Math.min(drag.current[0], dragEnd[0]) * 100 + "%",
            top: Math.min(drag.current[1], dragEnd[1]) * 100 + "%",
            width: Math.abs(drag.current[0] - dragEnd[0]) * 100 + "%",
            height: Math.abs(drag.current[1] - dragEnd[1]) * 100 + "%",
          }
        : null;
  return {
    key,
    setKey,
    keyInput,
    setKeyInput,
    authed,
    setAuthed,
    page,
    setPageState,
    state,
    setState,
    events,
    setEvents,
    devices,
    setDevices,
    samples,
    setSamples,
    adbPath,
    setAdbPath,
    address,
    setAddress,
    busy,
    setBusy,
    toast,
    setToast,
    connected,
    setConnected,
    imageUrl,
    setImageUrl,
    shownFrame,
    setShownFrame,
    label,
    setLabel,
    note,
    setNote,
    roi,
    setRoi,
    selected,
    setSelected,
    sampleImage,
    setSampleImage,
    replay,
    setReplay,
    replayImage,
    setReplayImage,
    report,
    setReport,
    confirm,
    setConfirm,
    dragEnd,
    setDragEnd,
    schema,
    setSchema,
    setPage,
    api,
    job,
    discover,
    control,
    taskControl,
    download,
    beginRoi,
    endRoi,
    saveSample,
    isLive,
    hasDevice,
    bounds,
    previewRef,
    drag,
    point,
  };
}
const Context = createContext<ReturnType<typeof useAppData> | null>(null);
export function AppProvider({ children }: { children: ReactNode }) {
  const value = useAppData();
  return <Context.Provider value={value}>{children}</Context.Provider>;
}
export function useApp() {
  const value = useContext(Context);
  if (!value) throw new Error("AppProvider is required");
  return value;
}
