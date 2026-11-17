/**
 * @fileoverview 实例运行总览页面（资源卡、调度器计划与实时日志）。
 */

import { Suspense, useState, useSyncExternalStore } from 'react'
import { useParams } from 'react-router-dom'
import type { Overview as OverviewData } from '../api/types'
import { useThemeComponent } from '../themes/context'
import { useInstanceOverview } from '../components/useInstanceOverview'
import { getLayout, subscribeLayout } from '../app/layout'
import { readSchedulerPosition, subscribeSchedulerPosition } from '../app/schedulerPositionPrefs'
import { ErrorBox, Loading } from '../components/ui'
import { MonitorPanel } from '../components/MonitorPanel'
import { defaultResourceKeys } from '../components/ResourceCards'
import { ModernRail } from '../components/ModernRail'
import { ModernRailResizeHandle } from '../components/ModernRailResizeHandle'
import { PluginPanels } from '../plugins/views'

function loadResourceSelection(instance: string) {
  try {
    const saved: unknown = JSON.parse(localStorage.getItem(`azurpilot.resources.${instance}`) ?? 'null')
    if (Array.isArray(saved) && saved.every(item => typeof item === 'string')) return [...new Set(saved)]
  } catch { /* 损坏偏好使用默认搭配。 */ }
  return defaultResourceKeys
}

/** 总览视图的共享数据契约：主题视图只负责展示，数据与偏好由路由控制器持有。 */
export interface OverviewViewProps {
  /** 当前实例名，用于标题与插件面板取数。 */
  instance: string
  /** 最近一次总览数据，来自 useInstanceOverview 的订阅。 */
  data: OverviewData
  /** 数据更新回调：视图内部刷新后写回控制器状态。 */
  onData: (data: OverviewData) => void
  /** 当前展示的资源卡 key 列表（已去重）。 */
  selectedResources: string[]
  /** 资源选择变化回调：控制器负责持久化。 */
  onResourcesChange: (keys: string[]) => void
}

/** 路由控制器在主题切换时保留数据订阅与资源偏好。 */
export function Overview() {
  const {instance = ''} = useParams()
  return <OverviewController key={instance} instance={instance}/>
}

function OverviewController({instance}: {instance: string}) {
  const View = useThemeComponent('Overview', ModernOverview)
  const [data, setData, error] = useInstanceOverview(instance, true, {notifyErrors: false})
  const [selectedResources, setSelectedResources] = useState<string[]>(() => loadResourceSelection(instance))

  function updateResourceSelection(keys: string[]) {
    const next = [...new Set(keys)]
    setSelectedResources(next)
    try { localStorage.setItem(`azurpilot.resources.${instance}`, JSON.stringify(next)) } catch { /* 无存储权限时仅本页生效。 */ }
  }

  if (error) return <ErrorBox message={error}/>
  if (!data) return <Loading/>
  return <Suspense fallback={<Loading/>}>
    <View instance={instance} data={data} onData={setData}
      selectedResources={selectedResources} onResourcesChange={updateResourceSelection}/>
  </Suspense>
}

/** 默认总览视图：调度器一列，日志 / 截图监控一列（舰R没有资源卡与统计页）。 */
export function ModernOverview({instance, data, onData}: OverviewViewProps) {
  const layout = useSyncExternalStore(subscribeLayout, getLayout, getLayout)
  const schedulerPosition = useSyncExternalStore(subscribeSchedulerPosition, readSchedulerPosition, readSchedulerPosition)
  return <div
    className={`instance-page-grid ${schedulerPosition === 'right' ? 'rail-right' : 'rail-left'}`}
    data-apu-component="overview"
    data-scheduler-position={schedulerPosition}
    style={layout.railWidth ? ({'--modern-rail-width': `${layout.railWidth}px`} as React.CSSProperties) : undefined}
  >
    <h1 className="modern-sr-title">{instance}</h1>
    <div className="instance-page-rail-wrap">
      <ModernRail instance={instance} data={data} onData={onData}/>
      <ModernRailResizeHandle side={schedulerPosition} />
    </div>
    <div className="instance-page-main">
      <PluginPanels instance={instance}/>
      <div className="instance-page-panel panel-rise">
        <MonitorPanel instance={instance}/>
      </div>
    </div>
  </div>
}
