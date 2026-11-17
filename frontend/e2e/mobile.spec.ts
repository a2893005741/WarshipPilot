import { expect, test, type Page } from '@playwright/test'

const subscriptions = new WeakMap<Page, string[][]>()

test.beforeEach(async ({page}) => {
  const topics: string[][] = []
  subscriptions.set(page, topics)
  page.on('websocket', socket => socket.on('framesent', frame => {
    const message = JSON.parse(frame.payload.toString())
    if (message.method === 'events.subscribe') topics.push(message.params.topics)
  }))
  await page.goto('/#key=mobile-e2e')
  await expect(page.locator('.mobile-bottom-nav')).toBeVisible()
  await expect(page.locator('.scheduler-toggle').first()).toBeEnabled()
  await page.screenshot({path: test.info().outputPath('mobile-overview.png'), animations: 'disabled'})
})

test('手机导航、任务抽屉与全局页面间返回', async ({page}) => {
  await page.getByRole('button', {name: '选择任务', exact: true}).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await page.screenshot({path: test.info().outputPath('mobile-tasks.png'), animations: 'disabled'})
  await dialog.getByRole('textbox', {name: '搜索任务', exact: true}).fill('远征')
  await dialog.locator('.task-submenu-item').first().click()
  await expect(dialog).not.toBeVisible()
  await expect(page).toHaveURL(/\/task\/expedition$/)
  await expect(page.locator('.task-config-modern')).toBeVisible()
  await page.getByRole('button', {name: '更多功能', exact: true}).click()
  await page.getByRole('dialog').getByRole('link', {name: '界面设置', exact: true}).click()
  await expect(page).toHaveURL(/\/interface$/)
  await page.getByRole('button', {name: '选择任务', exact: true}).click()
  await page.getByRole('dialog').getByRole('textbox', {name: '搜索任务', exact: true}).fill('远征')
  await page.getByRole('dialog').locator('.task-submenu-item').first().click()
  await expect(page).toHaveURL(/\/i\/[^/]+\/task\/expedition$/)
})

test('抽屉可点击遮罩关闭且键盘焦点不进入背景', async ({page}) => {
  await page.getByRole('button', {name: '更多功能', exact: true}).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.keyboard.press('Shift+Tab')
  expect(await page.getByRole('dialog').evaluate(node => node.contains(document.activeElement))).toBe(true)
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).not.toBeVisible()
  await page.getByRole('button', {name: '更多功能', exact: true}).click()
  await page.locator('.mobile-menu-backdrop').click({position: {x: 10, y: 10}})
  await expect(page.getByRole('dialog')).not.toBeVisible()
})

test('调度器可启停，日志与画面可切换', async ({page}) => {
  await page.locator('.scheduler-toggle').click()
  await expect(page.locator('[data-apu-component="scheduler"]')).toHaveAttribute('data-state', 'running')
  await page.locator('.scheduler-toggle').click()
  await expect(page.locator('[data-apu-component="scheduler"]')).toHaveAttribute('data-state', 'stopped')
  await page.getByRole('button', {name: '日志与画面', exact: true}).click()
  await expect(page.locator('.monitor-panel')).toBeVisible()
  await expect(page.locator('.instance-page-rail-wrap')).not.toBeVisible()
  await page.locator('.monitor-tabs button').nth(1).click()
  await expect(page.locator('.preview-stage')).toBeVisible()
  await expect.poll(() => subscriptions.get(page)?.at(-1)).toContain('preview')
  await page.getByRole('button', {name: '运行与任务', exact: true}).click()
  await expect.poll(() => subscriptions.get(page)?.at(-1)).not.toContain('preview')
  await page.getByRole('button', {name: '日志与画面', exact: true}).click()
  await expect.poll(() => subscriptions.get(page)?.at(-1)).toContain('preview')
})

test('小屏页面不横向溢出，参数可保存并重新读取', async ({page}) => {
  const base = new URL(page.url()).hash.slice(1).replace(/\/overview$/, '')
  await page.goto(`/#${base}/task/expedition`)
  const interval = page.locator('input[id="expedition.Scheduler.IntervalMinutes"]')
  await expect(interval).toBeVisible()
  await page.screenshot({path: test.info().outputPath('mobile-config.png'), animations: 'disabled'})
  await interval.fill('37')
  await interval.blur()
  await expect(page.locator('.edit-error')).toHaveCount(0)
  await expect.poll(async () => {
    const response = await page.request.get('/api/config?task=expedition', {headers: {Authorization: 'Bearer mobile-e2e'}})
    return (await response.json()).values.Scheduler.IntervalMinutes
  }).toBe(37)
  await page.reload()
  await expect(interval).toHaveValue('37')
  for (const width of [320, 390, 768, 950]) {
    await page.setViewportSize({width, height: 844})
    for (const path of ['/overview', '/task/expedition', '/task/sortie', '/device', '/tools/capture', '/tools/rules', '/tools/samples', '/tools/import']) {
      await page.goto(`/#${base}${path}`)
      await expect(page.locator(path === '/overview' ? '.instance-page-grid' : path.startsWith('/task/') ? '.task-config-modern' : '.warship-page')).toBeVisible()
      await expect(page.locator('[data-slot="loading"]')).toHaveCount(0)
      expect(await page.locator('main').evaluate(node => node.scrollWidth <= node.clientWidth + 1), `${width}px ${path}`).toBe(true)
    }
  }
})

test('桌面显示侧栏及双列总览', async ({page}) => {
  await page.setViewportSize({width: 1440, height: 1000})
  await expect(page.locator('.mobile-bottom-nav')).not.toBeVisible()
  await expect(page.locator('.sidebar')).toBeVisible()
  await expect(page.locator('.instance-page-rail-wrap')).toBeVisible()
  await expect(page.locator('.monitor-panel')).toBeVisible()
})

test('演习参数可保存，显示真实执行策略并可安排立刻运行', async ({page}) => {
  const base = new URL(page.url()).hash.slice(1).replace(/\/overview$/, '')
  await page.goto(`/#${base}/task/exercise`)
  const enabled = page.getByRole('switch', {name: '启用任务', exact: true})
  await expect(enabled).toBeEnabled()
  await enabled.click()
  await page.getByRole('combobox', {name: '演习舰队', exact: true}).click()
  await page.getByRole('option', {name: '第四舰队', exact: true}).click()
  await page.getByRole('combobox', {name: '演习阵型', exact: true}).click()
  await page.getByRole('option', {name: '单横', exact: true}).click()
  await expect(page.locator('[id="exercise.Scheduler.Runs"]')).toHaveCount(0)
  await expect(page.locator('[id="exercise.Exercise.演习夜战"]')).toHaveCount(0)
  await expect(page.locator('[id="exercise.Exercise.NightBattle"]')).toHaveValue('继续夜战')
  await expect(page.locator('[id="exercise.Exercise.Repair"]')).toHaveValue('沿用原演习快修')
  await expect.poll(async () => {
    const response = await page.request.get('/api/config?task=exercise', {headers: {Authorization: 'Bearer mobile-e2e'}})
    const values = (await response.json()).values
    return [values.Scheduler.Enable, values.Exercise.演习舰队, values.Exercise.演习阵型]
  }).toEqual([true, 3, 4])
  await page.reload()
  await expect(enabled).toBeChecked()
  await expect(page.getByRole('combobox', {name: '演习舰队', exact: true})).toHaveText('第四舰队')
  await page.getByRole('button', {name: '立刻运行', exact: true}).click()
  await expect.poll(async () => {
    const response = await page.request.get('/api/config?task=exercise', {headers: {Authorization: 'Bearer mobile-e2e'}})
    return (await response.json()).values.Scheduler.NextRun
  }).not.toBe('')
  await expect(page.locator('.edit-error')).toHaveCount(0)
  await page.screenshot({path: test.info().outputPath('exercise-config.png'), animations: 'disabled', fullPage: true})
})

test('手机可阅读全局设置和故障记录', async ({page}) => {
  await page.setViewportSize({width: 320, height: 740})
  for (const path of ['/settings', '/interface', '/updater', '/errors']) {
    await page.goto(`/#${path}`)
    await expect(page.locator('.modern-topbar-title')).toHaveText({
      '/settings': '系统设置', '/interface': '界面设置', '/updater': '更新器', '/errors': '故障记录',
    }[path]!)
    await expect(page.locator('[data-slot="loading"]')).toHaveCount(0)
    expect(await page.locator('main').evaluate(node => node.scrollWidth <= node.clientWidth + 1), path).toBe(true)
  }
})
