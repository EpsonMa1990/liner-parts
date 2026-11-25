export async function api(path, options = {}) {
  const headers = { 'X-Liner-Client': 'desktop', ...options.headers }
  let body = options.body
  if (body && !(body instanceof FormData)) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(body)
  }
  const response = await fetch('/api' + path, { ...options, headers, body })
  let data
  try { data = await response.json() } catch { throw new Error('无法读取本地服务响应，请重新打开应用。') }
  if (!response.ok) throw new Error(data.error || `操作失败（${response.status}）`)
  return data
}

export const statusNames = { pending: '待识别', recognized: '已识别', manual: '已校对', review: '待复核', error: '失败' }
export const imageAccept = '.png,.jpg,.jpeg,.webp,.bmp'
export function sortedFiles(files) {
  return Array.from(files).sort((a, b) => a.name.localeCompare(b.name, 'zh-CN', { numeric: true }))
}
export const categories = ['', '头', '身躯', '腰', '肩甲', '手臂', '左臂', '右臂', '腿', '脚', '左腿', '右腿', '武器1', '武器2', '武器3', '背包1', '背包2', '盾牌', '其他配件', '头-骨架', '身躯-骨架', '腰-骨架', '手臂-骨架', '腿-骨架']
