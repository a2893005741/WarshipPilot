/** Versioned ALAS-style request channel; images stay on authenticated HTTP. */
import {API_WS_PATH} from './generated';
export class ApiClient {
  private socket: WebSocket;
  private sequence = 0;
  private pending = new Map<
    number,
    {
      resolve: (value: any) => void;
      reject: (error: Error) => void;
      timer: number;
    }
  >();
  ready = false;
  constructor(key: string, onState: (value: any) => void, onClose: () => void) {
    this.socket = new WebSocket(
      `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}${API_WS_PATH}`,
    );
    this.socket.onopen = () => this.socket.send(JSON.stringify({ key }));
    this.socket.onmessage = (event) => {
      const value = JSON.parse(event.data);
      if (value.state) {
        this.ready = true;
        onState(value);
        return;
      }
      const entry = this.pending.get(value.id);
      if (!entry) return;
      clearTimeout(entry.timer);
      this.pending.delete(value.id);
      if (value.error) entry.reject(new Error(value.error.message));
      else entry.resolve(value.result);
    };
    this.socket.onclose = () => {
      this.ready = false;
      for (const entry of this.pending.values()) {
        clearTimeout(entry.timer);
        entry.reject(new Error("后台连接已断开"));
      }
      this.pending.clear();
      onClose();
    };
    this.socket.onerror = () => this.socket.close();
  }
  request(method: string, params: Record<string, unknown> = {}) {
    return new Promise<any>((resolve, reject) => {
      if (!this.ready) {
        reject(new Error("正在连接后台"));
        return;
      }
      const id = ++this.sequence;
      const timer = window.setTimeout(() => {
        this.pending.delete(id);
        reject(new Error("请求超时"));
      }, 90000);
      this.pending.set(id, { resolve, reject, timer });
      this.socket.send(
        JSON.stringify({ v: 1, type: "request", id, method, params }),
      );
    });
  }
  close() {
    this.socket.close();
  }
}
