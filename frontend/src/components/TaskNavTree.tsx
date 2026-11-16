import {
  Anchor,
  CalendarDays,
  ChevronDown,
  Search,
  Settings2,
  Swords,
  Wrench,
} from "lucide-react";
import { useEffect, useState } from "react";
import { useApp } from "../app/context";
const icons: Record<string, typeof Anchor> = {
  Warship: Settings2,
  DailyMission: CalendarDays,
  Farm: Swords,
  Decisive: Anchor,
  Tool: Wrench,
};
export function TaskNavTree() {
  const { schema, page, setPage } = useApp();
  const [search, setSearch] = useState(""),
    [open, setOpen] = useState<string[]>(["Warship", "DailyMission", "Farm"]);
  const groups = {
    ...schema?.menu,
    Tool: {
      name: "工具",
      tasks: { capture: [], samples: [], legacy: [], tasks: [] },
    },
  };
  const [collapsed, setCollapsed] = useState<string[]>([]);
  useEffect(() => setCollapsed([]), [page]);
  const toolLabels: Record<string, string> = {
    capture: "画面采集",
    samples: "页面样本",
    legacy: "原脚本素材",
    tasks: "配置导入",
  };
  const label = (id: string) => schema?.tasks[id]?.name || toolLabels[id] || id;
  return (
    <div className="task-nav-container">
      <div className="sidebar-label task-nav-heading">任务配置</div>
      <div className="input-icon wp-nav-search">
        <Search size={14} />
        <input
          aria-label="搜索任务"
          placeholder="搜索任务或选项…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>
      <nav className="task-nav">
        {Object.entries(groups).map(([key, group]) => {
          const tasks = Object.keys(group.tasks).filter((task) =>
            (
              label(task) +
              " " +
              task +
              " " +
              JSON.stringify(schema?.args[task] || {})
            )
              .toLowerCase()
              .includes(search.toLowerCase()),
          );
          if (!tasks.length) return null;
          const expanded =
              !!search ||
              (!collapsed.includes(key) &&
                (open.includes(key) || tasks.includes(page))),
            Icon = icons[key] || Anchor;
          return (
            <div className="task-group" key={key}>
              <button
                type="button"
                className={`task-group-button ${expanded ? "expanded" : ""} ${tasks.includes(page) ? "active" : ""}`}
                aria-expanded={expanded}
                onClick={() => {
                  if (expanded) {
                    setCollapsed((v) => [...v, key]);
                    setOpen((v) => v.filter((x) => x !== key));
                  } else {
                    setCollapsed((v) => v.filter((x) => x !== key));
                    setOpen((v) => [...v, key]);
                  }
                }}
              >
                <Icon size={18} className="task-group-icon" />
                <span className="task-group-title">{group.name}</span>
                <ChevronDown size={13} className="task-group-arrow" />
              </button>
              <div
                className={`task-submenu-list ${expanded ? "expanded" : ""}`}
              >
                <div className="task-submenu-inner">
                  {expanded &&
                    tasks.map((task) => (
                      <a
                        key={task}
                        href={`#/i/warship/${toolLabels[task] ? task : "task/" + task}`}
                        aria-current={page === task ? "page" : undefined}
                        className={`task-submenu-item ${page === task ? "active" : ""}`}
                        onClick={(e) => {
                          e.preventDefault();
                          setPage(task);
                        }}
                      >
                        <span className="task-submenu-label">
                          {label(task)}
                        </span>
                      </a>
                    ))}
                </div>
              </div>
            </div>
          );
        })}
      </nav>
    </div>
  );
}
