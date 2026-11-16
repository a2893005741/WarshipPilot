import { useApp } from "../app/context";
import UpdatePanel from "../components/UpdaterPanel";
export function Updater() {
  const { page, state, setState, setToast, api } = useApp();
  return (
    <div className="warship-utility">
      {page === "update" && (
        <div className="devices-layout">
          <UpdatePanel
            api={api}
            update={state?.update}
            onChanged={() => void api("state").then(setState)}
            onError={setToast}
          />
        </div>
      )}
    </div>
  );
}
