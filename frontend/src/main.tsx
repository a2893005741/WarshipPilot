/**
 * @fileoverview 前端应用主入口，初始化主题并挂载 React 根节点。
 */

import { Component, lazy, Suspense, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { createHashRouter, RouterProvider, Navigate } from 'react-router-dom'
import { App } from './app/App'
import { AppProvider } from './app/context'
import { PluginProvider } from './plugins/context'
import { PluginPage } from './plugins/views'
import { ThemeWallpaper } from './components/ThemeWallpaper'
import { applyTheme, getThemePreference } from './app/theme'
import { translateCurrentUi } from './i18n'
import { Capture, ConfigImport, Devices, LegacyRulesPage, Samples, WarshipLayout } from './warship/Layout'
import './styles/modern.css'
import './styles/minimal.css'
import './styles/shadcn.css'
import './plugins/styles.css'
import './styles/mobile.css'

// 顶层兜底与路由级兜底共用同一页：路由渲染出错时 React Router 会先接住，
// 没有 errorElement 就落到它自带的崩溃页（带堆栈），所以两级都要挂上。
function ErrorPage() {
  return <div className="welcome"><h1>{translateCurrentUi('error.pageTitle')}</h1><p>{translateCurrentUi('error.pageHint')}</p><button className="button primary" onClick={() => location.reload()}>{translateCurrentUi('error.reload')}</button></div>
}
class ErrorBoundary extends Component<{children: ReactNode}, {failed: boolean}> {
  state = {failed: false}
  static getDerivedStateFromError() { return {failed: true} }
  render() {
    if (this.state.failed) return <ErrorPage/>
    return this.props.children
  }
}
// WarshipPilot: AzurPilot's WebUI with the Azur Lane-only pages removed
// (statistics, stock exchange, fleets, scheduler programs, plugins page,
// remote access, announcements, multi-instance setup). One instance only.
const Overview = lazy(() => import('./pages/Overview').then(module => ({default: module.Overview})))
const TaskConfig = lazy(() => import('./pages/TaskConfig').then(module => ({default: module.TaskConfig})))
const Updater = lazy(() => import('./pages/Updater').then(module => ({default: module.Updater})))
const InterfaceSettings = lazy(() => import('./pages/InterfaceSettings').then(module => ({default: module.InterfaceSettings})))
const Settings = lazy(() => import('./pages/Settings').then(module => ({default: module.Settings})))
const ErrorRecords = lazy(() => import('./pages/ErrorRecords').then(module => ({default: module.ErrorRecords})))

const router = createHashRouter([
  {path: '/', element: <App/>, errorElement: <ErrorPage/>, children: [{path: 'errors', element: <ErrorRecords/>}, {path: 'interface', element: <InterfaceSettings/>}, {path: 'settings', element: <Settings/>}, {path: 'updater', element: <Updater/>}, {path: 'plugins/:pluginId/:pageId', element: <PluginPage/>}]},
  {path: '/i/:instance', element: <App/>, errorElement: <ErrorPage/>, children: [
    {index: true, element: <Navigate to="overview" replace/>},
    {path: 'overview', element: <Overview/>}, {path: 'task/:task', element: <TaskConfig/>},
    {path: 'errors', element: <Suspense fallback={<div>{translateCurrentUi('common.loading')}</div>}><ErrorRecords/></Suspense>},
    {path: 'logs', element: <Navigate to="../overview" replace/>}, {path: 'settings', element: <Navigate to="/settings" replace/>},
    // WarshipPilot device settings and developer tools.
    {element: <WarshipLayout/>, children: [
      {path: 'device', element: <Devices/>},
      {path: 'tools/capture', element: <Capture/>},
      {path: 'tools/rules', element: <LegacyRulesPage/>},
      {path: 'tools/samples', element: <Samples/>},
      {path: 'tools/import', element: <ConfigImport/>},
    ]},
  ]},
  {path: '*', element: <Navigate to="/" replace/>},
])
// 在挂载前应用已保存的主题，避免首屏闪过默认外观。
applyTheme(getThemePreference())
createRoot(document.getElementById('root')!).render(<ErrorBoundary><AppProvider><PluginProvider><ThemeWallpaper/><RouterProvider router={router}/></PluginProvider></AppProvider></ErrorBoundary>)
