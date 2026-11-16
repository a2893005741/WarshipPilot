import React, {useState} from 'react';
import {CloudDownload, RefreshCw, Save} from 'lucide-react';

export type UpdateState = {
  version:string; repo:string; has_token:boolean; auto_check:boolean; frozen:boolean;
  state:string; progress:string; error:string; checked:string;
  latest:null|{tag:string; version:string; name:string; notes:string; published:string; asset:null|{name:string; size:number}};
};

const label:Record<string,string> = {idle:'未检查', checking:'检查中', current:'已是最新版本', available:'有新版本',
  downloading:'下载中', extracting:'解压中', restarting:'正在重启', error:'出错'};

export default function UpdatePanel({api, update, onChanged, onError}:{
  api:(path:string, body?:any)=>Promise<any>; update?:UpdateState|null; onChanged:()=>void; onError:(m:string)=>void;
}) {
  const [repo, setRepo] = useState('');
  const [token, setToken] = useState('');
  if (!update) return null;
  const working = ['checking','downloading','extracting','restarting'].includes(update.state);
  const run = (path:string, body:any={}) => api(path, body).then(onChanged).catch(e=>onError(e.message));
  return <section className="panel update-panel">
    <div className="panel-head"><div><CloudDownload size={18}/><h2>软件更新</h2></div>
      <span className={update.state==='available'?'status-bad':'status-ok'}>{label[update.state]||update.state}{update.progress?` ${update.progress}`:''}</span></div>
    <div className="panel-body">
      <p>当前版本 <b>v{update.version}</b>{update.latest&&<> · 最新版本 <b>{update.latest.tag}</b>{update.latest.published&&` （${update.latest.published.slice(0,10)}）`}</>}</p>
      {update.latest?.notes&&update.state==='available'&&<pre className="release-notes">{update.latest.notes}</pre>}
      <div className="update-actions">
        <button className="secondary" disabled={working} onClick={()=>run('update-check')}><RefreshCw size={16}/>检查更新</button>
        <button className="primary" disabled={working||update.state!=='available'||!update.frozen}
          onClick={()=>run('update-install')}><CloudDownload size={16}/>下载并安装</button>
      </div>
      {!update.frozen&&<p className="hint">当前以源码运行，内置更新只在 EXE 版本中可用。</p>}
      <p className="hint">安装前需停止任务和调度器。安装时后台会退出、替换程序目录并自动重启，数据目录（配置、访问码、记录）保留；新版本启动失败会自动恢复旧版本。</p>
      {update.error&&<p className="hint error">{update.error}</p>}
      <details><summary>更新源设置</summary>
        <label>GitHub 仓库<input value={repo} placeholder={update.repo} onChange={e=>setRepo(e.target.value)}/></label>
        <label>只读访问令牌（私有仓库需要）{update.has_token&&<span className="status-ok"> · 已设置</span>}
          <input type="password" value={token} autoComplete="off" placeholder={update.has_token?'留空保持不变':'github_pat_…'} onChange={e=>setToken(e.target.value)}/></label>
        <label className="check"><input type="checkbox" checked={update.auto_check}
          onChange={e=>run('update-settings', {auto_check:e.target.checked})}/>启动后及每 6 小时自动检查</label>
        <div className="update-actions">
          <button className="secondary" onClick={()=>run('update-settings', {...(repo?{repo}:{}), ...(token?{token}:{})}).then(()=>{setToken('');setRepo('');})}><Save size={16}/>保存</button>
          {update.has_token&&<button className="secondary" onClick={()=>run('update-settings', {token:''})}>清除令牌</button>}
        </div>
        <p className="hint">令牌只保存在本机数据目录的 update.json，界面不会显示。建议使用 fine-grained token，只授予此仓库的 Contents 读取权限。</p>
      </details>
    </div>
  </section>;
}
