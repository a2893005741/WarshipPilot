import { useWarship } from "./context";
import LegacyRules from "./LegacyRules";
export function LegacyRulesPage() {
  const { state, setState, setToast, connected, api } = useWarship();
  return (
    <div className="warship-utility">
      {(
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
