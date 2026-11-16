import type { TaskConfig, Value } from "../api/types";
export type Edit = { value: Value; status: "saving" | "error"; error?: string };
/** Serialize edits so saves from independent fields cannot overwrite each other. */
export class EditQueue {
  edits: Record<string, Edit> = {};
  onChange?: (edits: Record<string, Edit>) => void;
  private tail: Promise<void> = Promise.resolve();
  constructor(
    private write: (path: string, value: Value) => Promise<TaskConfig>,
    private onSaved: (value: TaskConfig) => void,
  ) {}
  change(path: string, value: Value) {
    const entry: Edit = { value, status: "saving" };
    this.edits = { ...this.edits, [path]: entry };
    this.onChange?.(this.edits);
    this.tail = this.tail.then(async () => {
      try {
        const config = await this.write(path, value);
        this.onSaved(config);
        if (this.edits[path] === entry) {
          const next = { ...this.edits };
          delete next[path];
          this.edits = next;
        }
        window.dispatchEvent(new Event("wp-config-saved"));
      } catch (error) {
        if (this.edits[path] === entry)
          this.edits = {
            ...this.edits,
            [path]: { value, status: "error", error: (error as Error).message },
          };
      }
      this.onChange?.(this.edits);
    });
  }
  async settled() {
    await this.tail;
    if (Object.values(this.edits).some((e) => e.status === "error"))
      throw new Error("请先修正保存失败的配置项");
  }
}
