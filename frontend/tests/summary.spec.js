import { test, expect } from '@playwright/test'
import fs from 'node:fs'

test('grouped picking lists show per-part counts and merge across categories only in runner view', async ({ page }) => {
  await page.goto('/session?token=e2e-local-token')
  const headers = { 'X-Liner-Client': 'desktop' }
  const created = await page.request.post('/api/tasks/import', { headers, multipart: { file: { name: '汇总数量核对.pdf', mimeType: 'application/pdf', buffer: fs.readFileSync('../artifacts/e2e-manual.pdf') } } })
  expect(created.ok()).toBeTruthy()
  const task = await created.json()
  try {
  const box = (id, category, runner, part_number, quantity, status = 'manual') => ({ id, category, runner, part_number, quantity, status, x: .1, y: .1, width: .2, height: .1 })
  const pages = [
    [box('a','头','A1','03',2),box('b','头','A1','12',1),box('c','头','B','03',4),box('pending','头','A1','03',99,'pending')],
    [box('d','头','A1','03',3),box('e','左臂','A1','03',2),box('f','左臂','A1','2',1)]
  ]
  for (let i=0;i<2;i++) {
    const saved = await page.request.put(`/api/pages/${task.pages[i].id}`, { headers, data: { revision: 0, boxes: pages[i] } })
    expect(saved.ok()).toBeTruthy()
  }
  await page.reload()
  await page.getByRole('button', { name: new RegExp(task.title) }).first().click()
  await page.getByRole('button', { name: /取件汇总/ }).click()
  const table = page.getByRole('table')
  await expect(table.locator('tbody tr')).toHaveCount(3)
  const head = table.locator('tbody tr').filter({ has: page.getByRole('cell', { name: '头', exact: true }) }).filter({ has: page.getByRole('cell', { name: 'A1', exact: true }) })
  await expect(head).toContainText('03 × 5')
  await expect(head.locator('.summary-part')).toHaveText(['03 × 5', '12'])
  await expect(head.getByRole('cell', { name: '6 件', exact: true })).toBeVisible()
  await expect(table.locator('tfoot')).toContainText('合计 13 件 · 4 种零件 · 2 块板件')
  await page.screenshot({ path: '../artifacts/summary-by-category.png', fullPage: true })
  await page.getByRole('button', { name: '按板件汇总', exact: true }).click()
  await expect(table.locator('tbody tr')).toHaveCount(2)
  const runner = table.locator('tbody tr').filter({ has: page.getByRole('cell', { name: 'A1', exact: true }) })
  await expect(runner).toContainText('03 × 7')
  await expect(runner.getByRole('cell', { name: '9 件', exact: true })).toBeVisible()
  await expect(runner.locator('.summary-part')).toHaveText(['2','03 × 7','12'])
  await page.screenshot({ path: '../artifacts/summary-by-runner.png', fullPage: true })
  await page.getByRole('button', { name: '按部件汇总', exact: true }).click()
  await expect(table.locator('tbody tr')).toHaveCount(3)
  await page.setViewportSize({ width: 1000, height: 680 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
  } finally {
    await page.request.delete(`/api/tasks/${task.id}`, { headers })
  }
})
