// Share one rendered page between all row thumbnails, including unsaved boxes.
const pages = new Map()
export function pagePreview(pageId) {
  if (pages.has(pageId)) return pages.get(pageId)
  const image = new Image()
  const loaded = new Promise((resolve, reject) => {
    image.onload = () => resolve(image)
    image.onerror = () => { pages.delete(pageId); reject(new Error('页面截图加载失败')) }
  })
  image.src = `/api/pages/${pageId}/image`
  pages.set(pageId, loaded)
  if (pages.size > 3) pages.delete(pages.keys().next().value)
  return loaded
}
