/**
 * Layout of the WarshipPilot device and tool pages inside the ALAS shell.
 */
import { lazy } from "react";
import { Outlet } from "react-router-dom";
import { WarshipProvider, useWarship } from "./context";
import "./legacy.css";
import "./warship.css";

function Toast() {
  const { toast, setToast, busy } = useWarship();
  return <>
    {busy && <div role="status" className="toast">{busy}…</div>}
    {toast && !busy && <div role="alert" className="toast" onClick={() => setToast("")}>{toast}</div>}
  </>;
}

export function WarshipLayout() {
  return <WarshipProvider><div className="warship-page"><Outlet /></div><Toast /></WarshipProvider>;
}

export const Devices = lazy(() => import("./Devices").then(module => ({default: module.Devices})));
export const Capture = lazy(() => import("./Capture").then(module => ({default: module.Capture})));
export const LegacyRulesPage = lazy(() => import("./LegacyRulesPage").then(module => ({default: module.LegacyRulesPage})));
export const Samples = lazy(() => import("./Samples").then(module => ({default: module.Samples})));
export const ConfigImport = lazy(() => import("./ConfigImport").then(module => ({default: module.ConfigImport})));
