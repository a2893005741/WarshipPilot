import { useEffect, useRef } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { Dialog } from 'radix-ui'
import { Bug, Camera, Download, FileJson, Images, LayoutDashboard, ListChecks, Menu, MonitorSmartphone, Palette, Settings2, X } from 'lucide-react'
import { useApp } from '../app/context'
import { TaskNavTree } from './TaskNavTree'

export type MobileMenu = 'tasks' | 'more' | null

/** 手机导航复用原路由、任务树与鉴权；抽屉由 Radix 管理焦点、遮罩与 Esc。 */
export function MobileNavigation({instance, menu, onMenuChange, updateAvailable}: {
  instance?: string
  menu: MobileMenu
  onMenuChange: (menu: MobileMenu) => void
  updateAvailable: boolean
}) {
  const {instances} = useApp()
  const {pathname} = useLocation()
  const current = instance ?? instances[0]?.name
  const base = current ? `/i/${encodeURIComponent(current)}` : ''
  const close = () => onMenuChange(null)
  const opener = useRef<HTMLElement | null>(null)
  useEffect(() => {
    const media = window.matchMedia('(max-width: 950px)')
    const resize = () => { if (!media.matches) onMenuChange(null) }
    media.addEventListener('change', resize)
    return () => media.removeEventListener('change', resize)
  }, [onMenuChange])
  const moreActive = !instance || pathname.includes('/tools/') || pathname.endsWith('/errors')
  return <>
    <nav className="mobile-bottom-nav" aria-label="手机导航">
      {current && <NavLink to={`${base}/overview`} onClick={close}><LayoutDashboard size={21}/><span>总览</span></NavLink>}
      {current && <button type="button" className={pathname.includes('/task/') ? 'active' : ''} aria-label="选择任务" aria-haspopup="dialog" aria-expanded={menu === 'tasks'} onClick={() => onMenuChange('tasks')}><ListChecks size={21}/><span>任务</span></button>}
      {current && <NavLink to={`${base}/device`} onClick={close}><MonitorSmartphone size={21}/><span>设备</span></NavLink>}
      <button type="button" className={moreActive ? 'active' : ''} aria-label="更多功能" aria-haspopup="dialog" aria-expanded={menu === 'more'} onClick={() => onMenuChange('more')}><Menu size={21}/><span>更多{updateAvailable && <i className="tiny-dot teal"/>}</span></button>
    </nav>
    <Dialog.Root open={menu !== null} onOpenChange={open => {if (!open) close()}}>
      <Dialog.Portal>
        <Dialog.Overlay className="mobile-menu-backdrop"/>
        <Dialog.Content className="mobile-menu" aria-describedby={undefined} onOpenAutoFocus={() => {
          opener.current = document.activeElement as HTMLElement | null
        }} onCloseAutoFocus={event => {
          event.preventDefault()
          opener.current?.focus()
        }}>
          <div className="mobile-menu-heading">
            <div><span>舰R助手</span><Dialog.Title>{menu === 'tasks' ? '选择任务' : '更多功能'}</Dialog.Title></div>
            <Dialog.Close className="icon-button" aria-label="关闭导航"><X size={22}/></Dialog.Close>
          </div>
          {menu === 'tasks' && current ? <TaskNavTree onNavigate={close}/> : <nav className="primary-nav mobile-more-links" aria-label="更多功能">
            {current && <>
              <NavLink to={`${base}/tools/capture`} onClick={close}><Camera size={20}/>画面采集</NavLink>
              <NavLink to={`${base}/tools/rules`} onClick={close}><ListChecks size={20}/>识别规则</NavLink>
              <NavLink to={`${base}/tools/samples`} onClick={close}><Images size={20}/>样本管理</NavLink>
              <NavLink to={`${base}/tools/import`} onClick={close}><FileJson size={20}/>配置导入</NavLink>
            </>}
            <NavLink to="/errors" onClick={close}><Bug size={20}/>故障记录</NavLink>
            <NavLink to="/updater" onClick={close}><Download size={20}/>软件更新{updateAvailable && <span className="tiny-dot teal"/>}</NavLink>
            <NavLink to="/interface" onClick={close}><Palette size={20}/>界面设置</NavLink>
            <NavLink to="/settings" onClick={close}><Settings2 size={20}/>系统设置</NavLink>
          </nav>}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  </>
}
