import { ModernRail } from "../components/ModernRail";
import { MonitorPanel } from "../components/MonitorPanel";
export function Overview() {
  return (
    <div className="instance-page-grid">
      <div className="instance-page-rail-wrap">
        <ModernRail />
      </div>
      <div className="instance-page-main">
        <MonitorPanel />
      </div>
    </div>
  );
}
