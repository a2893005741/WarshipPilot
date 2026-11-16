export type Value = boolean | number | string;
export type Field = {
  name: string;
  help?: string;
  type: string;
  value: Value;
  storage: string;
  key?: string;
  display?: string;
  min?: number;
  max?: number;
  option?: { value: Value; label: string }[];
};
export type Schema = {
  menu: Record<string, { name: string; tasks: Record<string, string[]> }>;
  tasks: Record<string, { name: string; help: string; executable: boolean }>;
  groups: Record<string, string>;
  args: Record<string, Record<string, Record<string, Field>>>;
};
export type TaskConfig = {
  task: string;
  values: Record<string, Record<string, Value>>;
};
