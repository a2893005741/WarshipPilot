import { ListTree, Play, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { TaskConfig as Config } from "../api/types";
import { useApp } from "../app/context";
import { FieldInput } from "../components/FieldInput";
import { ModernRail } from "../components/ModernRail";
import { EditQueue, type Edit } from "../config/EditQueue";
export function TaskConfig({ task }: { task: string }) {
  const { schema, api, setToast, taskControl, busy } = useApp();
  const [config, setConfig] = useState<Config>(),
    [search, setSearch] = useState(""),
    [error, setError] = useState(""),
    [edits, setEdits] = useState<Record<string, Edit>>({});
  const queue = useMemo(
    () =>
      new EditQueue(
        (path, value) => api("config-field", { path, value }),
        setConfig,
      ),
    [task],
  );
  useEffect(() => {
    queue.onChange = setEdits;
    let active = true;
    void api("config?task=" + encodeURIComponent(task))
      .then((value) => {
        if (active) setConfig(value);
      })
      .catch((e) => setError(e.message));
    return () => {
      active = false;
      queue.onChange = undefined;
    };
  }, [task, queue]);
  const groups = Object.entries(schema?.args[task] || {})
    .map(([name, fields]) => ({
      name,
      fields: Object.entries(fields).filter(([key, field]) =>
        (field.name + " " + key).toLowerCase().includes(search.toLowerCase()),
      ),
    }))
    .filter((group) => group.fields.length);
  const run = async () => {
    try {
      await queue.settled();
      await taskControl("start", task);
    } catch (e) {
      setToast((e as Error).message);
    }
  };
  return (
    <div className="task-config-page task-config-modern">
      <h1 className="modern-sr-title">{schema?.tasks[task].name}</h1>
      <div className="task-config-settings">
        <div className="task-config-settings-inner">
          <div className="config-toolbar">
            <div className="input-icon">
              <Search size={17} />
              <input
                aria-label="搜索配置"
                placeholder="搜索当前任务的配置…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            <select
              className="wp-group-switcher"
              aria-label="跳转参数分组"
              defaultValue=""
              onChange={(e) =>
                document
                  .getElementById("group-" + e.target.value)
                  ?.scrollIntoView({ block: "start" })
              }
            >
              <option value="" disabled>
                参数目录
              </option>
              {groups.map((g) => (
                <option key={g.name} value={g.name}>
                  {schema?.groups[g.name]}
                </option>
              ))}
            </select>
            {schema?.tasks[task].executable && (
              <button
                className="button primary"
                disabled={!!busy}
                onClick={() => void run()}
              >
                <Play size={15} />
                运行一次
              </button>
            )}
          </div>
          {error && (
            <div className="error-message" role="alert">
              {error}
            </div>
          )}
          <div className="config-groups">
            <section className="panel task-help-panel">
              <p className="task-help">{schema?.tasks[task].help}</p>
            </section>
            {config ? (
              groups.map((group) => (
                <section
                  className="panel config-group"
                  key={group.name}
                  id={`group-${group.name}`}
                >
                  <div className="panel-heading">
                    <div>
                      <span className="group-indicator" />
                      <h2>{schema?.groups[group.name]}</h2>
                    </div>
                  </div>
                  {group.fields.map(([key, field]) => {
                    const path = `${task}.${group.name}.${key}`,
                      edit = edits[path],
                      value =
                        edit?.value ??
                        config.values[group.name]?.[key] ??
                        field.value;
                    return (
                      <div className="field-row" key={key}>
                        <div className="field-label">
                          <label htmlFor={path}>
                            {field.name}
                            {field.display === "readonly" && (
                              <span className="small-label">只读</span>
                            )}
                          </label>
                          {field.help && <p>{field.help}</p>}
                        </div>
                        <div className="field-control">
                          <FieldInput
                            id={path}
                            field={field}
                            value={value}
                            invalid={edit?.status === "error"}
                            onChange={(v) => queue.change(path, v)}
                          />
                          {edit?.status === "error" && (
                            <div className="edit-status" role="alert">
                              {edit.error}
                            </div>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </section>
              ))
            ) : (
              <p className="muted">正在读取配置…</p>
            )}
            {!groups.length && (
              <div className="rail-empty">没有匹配的配置项</div>
            )}
          </div>
        </div>
      </div>
      <aside
        className="task-config-directory task-rail-directory instance-page-rail"
        aria-label="参数目录"
      >
        <div className="rail-section-heading">
          <div>
            <ListTree size={15} />
            <span>参数目录</span>
          </div>
        </div>
        <nav className="group-nav">
          {groups.map((group) => (
            <a
              key={group.name}
              href={`#group-${group.name}`}
              onClick={(e) => {
                e.preventDefault();
                document
                  .getElementById("group-" + group.name)
                  ?.scrollIntoView({ behavior: "smooth", block: "start" });
              }}
            >
              {schema?.groups[group.name]}
            </a>
          ))}
        </nav>
      </aside>
      <div className="task-config-rail-slot">
        <div className="instance-page-rail-wrap">
          <ModernRail />
        </div>
      </div>
    </div>
  );
}
