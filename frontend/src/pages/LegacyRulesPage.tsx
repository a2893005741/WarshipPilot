import { useApp } from "../app/context";
import LegacyRules from "../components/LegacyRules";
export function LegacyRulesPage() {
  const { page, state, setState, setToast, connected, api } = useApp();
  return (
    <div className="warship-utility">
      {page === "legacy" && (
        <LegacyRules
          api={api}
          live={state?.legacy}
          hasFrame={!!state?.frame}
          backendOnline={connected}
          onSaved={() => void api("state").then(setState)}
          onError={setToast}
        />
      )}
    </div>
  );
}
