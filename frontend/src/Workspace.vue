<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ArrowLeft, Check, CheckCheck, ChevronLeft, ChevronRight, Download, FileArchive, Focus, Images, ListChecks, LoaderCircle, Maximize2, MousePointer2, Plus, Save, ScanLine, SquareDashedMousePointer, StopCircle, Table2, Trash2, Undo2, ZoomIn, ZoomOut } from 'lucide-vue-next'
import { api, categories, imageAccept, sortedFiles, statusNames } from './api'
import MarkerCanvas from './MarkerCanvas.vue'
import CropThumbnail from './CropThumbnail.vue'
import Dialog from './Dialog.vue'
import ShareDialog from './ShareDialog.vue'

const props = defineProps({ taskId: String })
const emit = defineEmits(['back', 'updated', 'settings', 'notice'])
const task = ref(null), page = ref(null), selected = ref(''), tab = ref('edit'), zoom = ref(100), mode = ref('draw')
const dirty = ref(false), saving = ref(false), error = ref(''), saveError = ref(''), busy = ref(false), summary = ref(null), dialog = ref('')
const jobs = ref([]), dismissedJobs = ref([]), generation = ref(0), undo = ref([]), filter = ref('all'), active = ref(true)
const imageFiles = ref(null), detailSource = ref(''), detailFailed = ref(false), appending = ref(false)
const noPartsReason = ref('')
const summaryMode = ref('category')
const summaryRows = computed(() => summary.value?.[summaryMode.value === 'category' ? 'by_category' : 'by_runner'] || [])
const confirmedPages = computed(() => task.value?.pages.filter(p => p.confirmed_revision === p.revision).length || 0)
async function openShare() { await perform(async () => { await flush(); dialog.value = 'share' }) }
async function confirmPage() {
  viewEpoch++
  busy.value = true
  await perform(async () => {
    await flush()
    page.value = await api('/pages/' + page.value.id + '/confirm', { method: 'POST', body: { revision: page.value.revision, no_parts_reason: noPartsReason.value } })
    await refreshTask(); dialog.value = ''; noPartsReason.value = ''
    emit('notice', '本页已确认完成。修改内容后需重新确认。')
  })
  busy.value = false
}
let timer, poller, savePromise, previewTimer, polling = false, jobsEpoch = 0, viewEpoch = 0
const jobStates = { queued: '排队中', running: '识别中', cancelling: '取消中', cancelled: '已取消', completed: '已完成', partial: '部分失败', failed: '失败', interrupted: '已中断' }
function isActive(job) { return ['queued','running','cancelling'].includes(job.status) }
const isRunning = computed(() => jobs.value.some(isActive))
const visibleJobs = computed(() => jobs.value.filter(job => !dismissedJobs.value.includes(job.id)).sort((a, b) => Number(!isActive(a)) - Number(!isActive(b))))
const runningCount = computed(() => jobs.value.filter(job => ['running','cancelling'].includes(job.status)).length)
const queuedCount = computed(() => jobs.value.filter(job => job.status === 'queued').length)
function jobForPage(id) { return jobs.value.find(job => isActive(job) && job.page_ids.includes(id)) }
const pageJob = computed(() => page.value ? jobForPage(page.value.id) : null)
const locked = computed(() => !!pageJob.value || busy.value)
function jobPages(job) { const pages = job.page_numbers; return !pages.length ? '说明书' : pages.length <= 3 ? `第 ${pages.join('、')} 页` : `第 ${pages.slice(0,3).join('、')}…页（共 ${pages.length} 页）` }
function dismissFinished() { dismissedJobs.value = [...new Set([...dismissedJobs.value, ...jobs.value.filter(job => !isActive(job)).map(job => job.id)])] }
const selectedBox = computed(() => page.value?.boxes.find(b => b.id === selected.value))
const quantityDraft = ref('')
watch([selected, () => selectedBox.value?.quantity], ([, value]) => quantityDraft.value = value == null ? '' : String(value), { immediate: true })
const selectedIndex = computed(() => page.value?.boxes.findIndex(b => b.id === selected.value) ?? -1)
const previewUrl = computed(() => {
  if (!selectedBox.value || !page.value) return ''
  const params = new URLSearchParams(Object.fromEntries(['x','y','width','height'].map(key => [key, selectedBox.value[key]])))
  return `/api/pages/${page.value.id}/crop?${params}`
})
watch(previewUrl, url => {
  clearTimeout(previewTimer); detailSource.value = ''; detailFailed.value = false
  previewTimer = setTimeout(() => detailSource.value = url, 140)
})
const pageIndex = computed(() => page.value?.page_index ?? 0)
const visibleBoxes = computed(() => (page.value?.boxes || []).filter(b => filter.value === 'all' || ['pending','review','error'].includes(b.status)))
const missing = computed(() => page.value?.boxes.filter(b => !['recognized','manual'].includes(b.status)).length || 0)
async function refreshTask() { task.value = await api('/tasks/' + props.taskId); emit('updated') }
async function loadPage(id) {
  if (busy.value) return
  viewEpoch++
  busy.value = true; error.value = ''
  try { await flush(); page.value = await api('/pages/' + id); selected.value = ''; undo.value = []; filter.value = 'all' }
  finally { busy.value = false }
}
async function navigatePage(id) { try { await loadPage(id) } catch (e) { error.value = e.message } }
async function appendImages(event) {
  const inputs = sortedFiles(event.target.files)
  if (!inputs.length || busy.value) return
  viewEpoch++
  busy.value = true; appending.value = true
  await perform(async () => {
    await flush()
    const data = new FormData(); inputs.forEach(input => data.append('file', input))
    const result = await api('/tasks/' + props.taskId + '/images', { method: 'POST', body: data })
    task.value = result; emit('updated')
    page.value = await api('/pages/' + result.pages[result.pages.length-inputs.length].id)
    selected.value = ''; undo.value = []; filter.value = 'all'; tab.value = 'edit'
    emit('notice', `已追加 ${inputs.length} 页图片，可继续框选标记。`)
  })
  busy.value = false; appending.value = false; event.target.value = ''
}
function changed(boxes) {
  if (locked.value) return
  undo.value = [...undo.value.slice(-29), structuredClone(page.value.boxes.map(b => ({ ...b })))]
  page.value.boxes = boxes
  touch()
}
function touch() {
  dirty.value = true; generation.value++; saveError.value = ''
  clearTimeout(timer); timer = setTimeout(() => flush().catch(() => {}), 650)
}
function edit(field, value) {
  if (!selectedBox.value || locked.value) return
  const box = { ...selectedBox.value, [field]: value }
  if (['runner','part_number'].includes(field)) box.status = box.runner.trim() && box.part_number.trim() ? 'manual' : 'review'
  changed(page.value.boxes.map(b => b.id === box.id ? box : b))
}
function remove(id) { if (!locked.value) { changed(page.value.boxes.filter(b => b.id !== id)); selected.value = '' } }
function undoLast() {
  if (!undo.value.length || locked.value) return
  page.value.boxes = undo.value.pop(); selected.value = ''; touch()
}
function addBox() {
  if (locked.value) return
  const box = { id: crypto.randomUUID(), x: .3, y: .3, width: .2, height: .07, category: '', quantity: 1, runner: '', part_number: '', raw_text: '', note: '', status: 'pending' }
  changed([...page.value.boxes, box]); selected.value = box.id
}
function confirmBox() {
  if (locked.value || !selectedBox.value) return
  if (!selectedBox.value.runner.trim() || !selectedBox.value.part_number.trim()) { error.value = '请填写板件和零件号后再确认。'; return }
  changed(page.value.boxes.map(b => b.id === selected.value ? { ...b, status: 'manual', note: '' } : b))
}
function inputQuantity(event) {
  quantityDraft.value = event.target.value
  const value = Number(quantityDraft.value)
  if (quantityDraft.value !== '' && Number.isInteger(value) && value >= 1 && value <= 9999 && value !== selectedBox.value.quantity) edit('quantity', value)
}
function setQuantity(event) {
  const value = Number(event.target.value)
  if (!Number.isInteger(value) || value < 1 || value > 9999) {
    error.value = '数量需要填写 1 到 9999 之间的整数。'
    quantityDraft.value = String(selectedBox.value.quantity)
    event.target.value = selectedBox.value.quantity
    return
  }
  error.value = ''
  if (value !== selectedBox.value.quantity) edit('quantity', value)
}
function fill(field, scope) {
  if (!selectedBox.value || locked.value) return
  const value = selectedBox.value[field]
  if (field === 'category' && !value) return
  const index = selectedIndex.value
  changed(page.value.boxes.map((box, i) => scope === 'all' || i > index ? { ...box, [field]: value } : box))
}
async function flush() {
  clearTimeout(timer)
  if (savePromise) { await savePromise; if (dirty.value) return flush(); return }
  if (!dirty.value || !page.value) return
  saving.value = true
  savePromise = (async () => {
    while (dirty.value) {
      const stamp = generation.value
      const payload = { revision: page.value.revision, boxes: JSON.parse(JSON.stringify(page.value.boxes)) }
      const result = await api('/pages/' + page.value.id, { method: 'PUT', body: payload })
      page.value.revision = result.revision
      page.value.confirmed_revision = result.confirmed_revision
      if (stamp === generation.value) { dirty.value = false; page.value.boxes = result.boxes }
    }
    saveError.value = ''; await refreshTask()
  })()
  try { await savePromise } catch (e) { saveError.value = e.message; throw e }
  finally { saving.value = false; savePromise = null }
}
async function perform(fn) {
  error.value = ''
  try { return await fn() } catch (e) { error.value = e.message }
}
async function showSummary() {
  await perform(async () => { await flush(); summary.value = await api('/tasks/' + props.taskId + '/summary'); tab.value = 'summary' })
}
async function startRecognition(options) {
  if (busy.value) return
  jobsEpoch++; busy.value = true
  dialog.value = ''; error.value = ''
  await perform(async () => {
    await flush()
    const submitted = await api('/tasks/' + props.taskId + '/recognize', { method: 'POST', body: options })
    jobs.value = [...jobs.value.filter(job => job.id !== submitted.id), submitted]
    schedulePoll()
  })
  busy.value = false
}
function schedulePoll() {
  clearTimeout(poller)
  poller = setTimeout(poll, 900)
}
async function poll() {
  if (!active.value || polling) return
  polling = true
  let repeat = false
  const epoch = jobsEpoch, view = viewEpoch, pageId = page.value?.id, stamp = generation.value, revision = page.value?.revision
  try {
    const state = await api('/tasks/' + props.taskId + '/recognition-state' + (pageId ? '?page_id=' + pageId : ''))
    if (!active.value) return
    if (epoch !== jobsEpoch || view !== viewEpoch || busy.value) { repeat = true; return }
    const canApply = state.page && page.value?.id === pageId && stamp === generation.value && revision === page.value.revision && !dirty.value && !saving.value
    // Keep the current page locked until its final results and revision are installed together.
    if (pageJob.value && !canApply) { repeat = true; return }
    if (canApply) {
      if (state.page.revision !== revision) undo.value = []
      page.value = state.page
    }
    const previous = jobs.value.map(job => `${job.id}:${job.status}:${job.done}`).join('|')
    jobs.value = state.jobs
    if (previous !== state.jobs.map(job => `${job.id}:${job.status}:${job.done}`).join('|')) {
      await refreshTask()
      if (tab.value === 'summary') summary.value = await api('/tasks/' + props.taskId + '/summary')
    }
  } catch (e) { if (active.value) error.value = e.message; repeat = true }
  finally { polling = false; if (active.value && (repeat || isRunning.value)) schedulePoll() }
}
async function cancel(jobId) {
  jobsEpoch++
  await perform(async () => {
    await api('/jobs/' + jobId + '/cancel', { method: 'POST', body: {} })
    // A fresh snapshot unlocks the page and prevents stale in-flight polling from reverting it.
    schedulePoll()
  })
}
async function exportFile(kind) {
  await perform(async () => {
    await flush()
    if (window.pywebview?.api?.save_export) {
      const result = await window.pywebview.api.save_export(props.taskId, kind)
      if (result.error) throw new Error(result.error)
      if (result.saved) emit('notice', `已保存 ${result.name}`)
    } else {
      const a = document.createElement('a'); a.href = `/api/tasks/${props.taskId}/export/${kind}`; a.download = ''; a.click()
    }
  })
}
async function back() { await perform(async () => { await flush(); emit('back') }) }
function beforeUnload(event) { if (dirty.value) { event.preventDefault(); event.returnValue = '' } }
onMounted(async () => {
  await perform(async () => {
    task.value = await api('/tasks/' + props.taskId)
    jobs.value = task.value.jobs || []
    if (task.value.pages.length) await loadPage(task.value.pages[0].id)
    if (isRunning.value) schedulePoll()
  })
  window.addEventListener('beforeunload', beforeUnload)
})
onUnmounted(() => { active.value = false; clearTimeout(timer); clearTimeout(poller); clearTimeout(previewTimer); window.removeEventListener('beforeunload', beforeUnload) })
defineExpose({ flush })
</script>

<template>
  <section class="workspace">
    <header class="work-header">
      <button class="icon-btn" aria-label="返回任务列表" @click="back"><ArrowLeft :size="20" /></button>
      <div class="work-title"><span class="eyebrow">取件表工作台</span><h1>{{ task?.title || '正在打开…' }}</h1></div>
      <span class="save-state" :class="{ error: saveError }" role="status"><LoaderCircle v-if="saving" :size="14" class="spin" /><Check v-else-if="!dirty" :size="14" />{{ saveError ? '保存失败' : saving ? '正在保存' : dirty ? '尚未保存' : '已保存到本机' }}</span>
      <button class="secondary append-images" aria-label="追加图片" title="可多选，按文件名数字顺序追加到本任务" :disabled="busy" @click="imageFiles.click()"><LoaderCircle v-if="appending" :size="16" class="spin" /><Images v-else :size="16" /><span>{{ appending ? '正在导入' : '追加图片' }}</span></button>
      <button class="secondary" :disabled="isRunning || busy" @click="exportFile('liner')"><FileArchive :size="16" /><span>备份项目</span></button>
      <button class="primary" :disabled="isRunning || busy || !task?.box_count" @click="exportFile('xlsx')"><Download :size="16" /><span>导出 Excel</span></button>
      <button class="secondary" :disabled="busy" @click="openShare">分享广场</button>
    </header>
    <div v-if="saveError" class="notice error banner" role="alert">{{ saveError }}<button class="text-btn" @click="perform(flush)"><Save :size="14" />重试保存</button></div>
    <div v-if="error" class="notice error banner" role="alert">{{ error }}<button class="text-btn" @click="emit('settings')">接口设置</button><button class="text-btn" @click="error = ''">收起</button></div>
    <section v-if="visibleJobs.length" class="recognition-queue" aria-label="识别队列">
      <header><span>后台识别 · 进行中 {{ runningCount }} · 排队 {{ queuedCount }}</span><button class="text-btn" @click="dismissFinished">收起已完成</button></header>
      <div class="queue-items"><div v-for="job in visibleJobs" :key="job.id" class="job-strip" :class="{ active: isActive(job) }" :data-job-id="job.id" role="status">
        <LoaderCircle v-if="isActive(job)" :size="16" class="spin" /><CheckCheck v-else :size="16" /><span class="job-description"><strong>{{ jobPages(job) }} · {{ jobStates[job.status] }}</strong><small>{{ job.message || '等待空闲识别线程…' }}</small></span><span class="mono">{{ job.done }} / {{ job.total }}</span>
        <progress :value="job.done" :max="job.total" :aria-label="`${jobPages(job)}识别进度`" />
        <button v-if="isActive(job)" class="text-btn" :disabled="job.status === 'cancelling'" :aria-label="`取消${jobPages(job)}识别`" @click="cancel(job.id)"><StopCircle :size="16" />取消</button><button v-else class="text-btn" :aria-label="`收起${jobPages(job)}识别结果`" @click="dismissedJobs.push(job.id)">收起</button>
      </div></div>
    </section>
    <nav class="workspace-tabs" aria-label="工作台视图"><button :class="{ active: tab === 'edit' }" @click="tab = 'edit'"><ScanLine :size="17" />说明书标注</button><button :class="{ active: tab === 'summary' }" @click="showSummary"><Table2 :size="17" />取件汇总<span v-if="task?.ready_count" class="count">{{ task.ready_count }}</span></button><span class="workspace-tip">{{ task?.page_count || 0 }} 页说明书 · {{ task?.box_count || 0 }} 个标记</span></nav>
    <div v-if="page && task" class="completion-strip"><span>全模型逐页校对 {{ confirmedPages }} / {{ task.page_count }} · 修改后需重新确认</span><button class="text-btn" :disabled="locked || (!dirty && page.confirmed_revision === page.revision)" @click="noPartsReason = page.no_parts_reason || ''; dialog = 'confirm-page'">{{ !dirty && page.confirmed_revision === page.revision ? '本页已确认完成' : '确认本页完成' }}</button></div>
    <div v-if="tab === 'edit' && page && task" class="editor-grid">
      <aside class="page-rail" aria-label="说明书页码"><span class="rail-label">页面</span><button v-for="p in task.pages" :key="p.id" :class="{ active: p.id === page.id }" :aria-label="`第 ${p.page_index+1} 页`" :aria-current="p.id === page.id ? 'page' : undefined" @click="navigatePage(p.id)"><img :src="`/api/pages/${p.id}/image?thumb=1`" :alt="`第 ${p.page_index+1} 页缩略图`" loading="lazy"><span>{{ String(p.page_index+1).padStart(2,'0') }}</span><small v-if="jobForPage(p.id)" class="page-job-label">{{ jobStates[jobForPage(p.id).status] }}</small><i v-else-if="p.ready_count" class="page-dot" /></button></aside>
      <div class="canvas-pane">
        <div class="canvas-toolbar"><div class="segmented"><button class="icon-btn" :class="{ active: mode === 'draw' }" aria-label="画框模式" title="画框模式" :disabled="locked" @click="mode = 'draw'"><SquareDashedMousePointer :size="18" /></button><button class="icon-btn" :class="{ active: mode === 'select' }" aria-label="选择模式" title="选择模式" @click="mode = 'select'"><MousePointer2 :size="18" /></button></div><button class="icon-btn" :disabled="locked || !undo.length" aria-label="撤销上次标注修改" title="撤销" @click="undoLast"><Undo2 :size="18" /></button><span class="toolbar-spacer" /><button class="icon-btn" aria-label="缩小" :disabled="zoom <= 50" @click="zoom -= 25"><ZoomOut :size="18" /></button><button class="zoom-value" aria-label="恢复适合宽度" @click="zoom = 100">{{ zoom }}%</button><button class="icon-btn" aria-label="放大" :disabled="zoom >= 250" @click="zoom += 25"><ZoomIn :size="18" /></button></div>
        <MarkerCanvas :key="page.id" :page="page" :boxes="page.boxes" :selected="selected" :disabled="locked" :zoom="zoom" :mode="mode" @change="changed" @select="selected = $event" @delete="remove" />
        <footer class="canvas-footer"><span>{{ mode === 'draw' ? '拖动框选完整零件编号' : '点击选框，拖动调整位置' }}<span class="wide-hint"> · 方向键微调 · Delete 删除</span></span><div><button class="icon-btn" aria-label="上一页" :disabled="pageIndex === 0" @click="navigatePage(task.pages[pageIndex-1].id)"><ChevronLeft :size="17" /></button><span class="mono">{{ pageIndex+1 }} / {{ task.page_count }}</span><button class="icon-btn" aria-label="下一页" :disabled="pageIndex === task.page_count-1" @click="navigatePage(task.pages[pageIndex+1].id)"><ChevronRight :size="17" /></button></div></footer>
      </div>
      <aside class="inspector">
        <header class="inspector-header"><div><h2>本页标记 <span class="count">{{ page.boxes.length }}</span></h2><p>一个框对应一个完整零件标号</p></div><button class="icon-btn" :disabled="locked" aria-label="添加标记框" title="添加标记框，可用方向键移动" @click="addBox"><Plus :size="20" /></button></header>
        <div class="recognize-actions"><button class="primary" :disabled="locked || !page.boxes.length" @click="startRecognition({ page_id: page.id, mode: 'pending' })"><LoaderCircle v-if="pageJob" :size="17" class="spin" /><ScanLine v-else :size="17" />{{ pageJob ? pageJob.status === 'queued' ? '本页排队中' : '本页识别中' : '识别本页未完成项' }}</button><button class="secondary" :disabled="busy || !task.box_count" aria-label="更多识别选项" @click="dialog = 'recognize'"><ListChecks :size="18" /></button></div>
        <p v-if="pageJob" class="page-job-hint">本页已提交识别；可以切换其他页面继续画框和提交。</p>
        <div class="list-filter"><button :class="{ active: filter === 'all' }" @click="filter = 'all'">全部 {{ page.boxes.length }}</button><button :class="{ active: filter === 'review' }" @click="filter = 'review'">待处理 {{ missing }}</button></div>
        <div class="box-list" role="list" aria-label="标记列表">
          <div v-if="!visibleBoxes.length" class="box-empty"><Focus :size="30" /><p>{{ page.boxes.length ? '本页标记已处理' : '先框住一个零件标号' }}</p><small>{{ page.boxes.length ? '你可以继续下一页或查看汇总。' : '在左侧说明书上拖动，或点击右上角 +。' }}</small></div>
          <button v-for="box in visibleBoxes" :key="box.id" class="box-row" :class="{ active: selected === box.id }" @click="selected = box.id"><span class="box-index">{{ String(page.boxes.indexOf(box)+1).padStart(2,'0') }}</span><CropThumbnail :page="page" :box="box" :number="page.boxes.indexOf(box)+1" /><span class="box-content"><strong>{{ box.runner && box.part_number ? `${box.runner} (${box.part_number})` : box.raw_text || '未识别的标号' }}</strong><small>{{ box.category || '未分类' }} · {{ box.quantity }} 件</small></span><span class="status" :class="box.status">{{ statusNames[box.status] }}</span></button>
        </div>
        <form v-if="selectedBox" class="box-editor" @submit.prevent="confirmBox">
          <div class="box-editor-title"><h3>编辑标记 {{ page.boxes.findIndex(b => b.id === selected)+1 }}</h3><button class="icon-btn danger" type="button" :disabled="locked" aria-label="删除当前标记" @click="remove(selected)"><Trash2 :size="17" /></button></div>
          <button class="crop-detail" type="button" aria-label="放大当前截图" :disabled="!detailSource || detailFailed" @click="dialog = 'crop'"><span class="crop-detail-label">截图对照 <Maximize2 :size="13" /></span><img v-if="detailSource && !detailFailed" :key="detailSource" :src="detailSource" alt="当前标记截图" @error="detailFailed = true"><span v-else class="crop-placeholder">{{ detailFailed ? '截图加载失败，请重新选择标记' : '正在准备截图…' }}</span></button>
          <fieldset :disabled="locked">
            <div class="form-grid"><label class="field">板件<input :value="selectedBox.runner" aria-label="板件" placeholder="例如 A1" maxlength="80" @input="edit('runner', $event.target.value)"></label><label class="field">零件号<input :value="selectedBox.part_number" aria-label="零件号" placeholder="例如 12" maxlength="80" @input="edit('part_number', $event.target.value)"></label></div>
            <div class="fill-control">
              <label class="field">分类<select :value="selectedBox.category" aria-label="分类" @change="edit('category', $event.target.value)"><option v-for="c in categories" :key="c" :value="c">{{ c || '请选择分类' }}</option><option v-if="!categories.includes(selectedBox.category)" :value="selectedBox.category">{{ selectedBox.category }}（已有分类）</option></select></label>
              <div class="fill-actions"><button class="text-btn" type="button" aria-label="分类全部填充" :disabled="!selectedBox.category" @click="fill('category', 'all')">全部填充</button><button class="text-btn" type="button" aria-label="分类往下填充" :disabled="!selectedBox.category || selectedIndex === page.boxes.length-1" @click="fill('category', 'down')">往下填充</button></div>
            </div>
            <div class="fill-control">
              <label class="field">数量<input :value="quantityDraft" aria-label="数量" type="number" min="1" max="9999" step="1" required @input="inputQuantity" @change="setQuantity"></label>
              <div class="fill-actions"><button class="text-btn" type="button" aria-label="数量全部填充" @click="fill('quantity', 'all')">全部填充</button><button class="text-btn" type="button" aria-label="数量往下填充" :disabled="selectedIndex === page.boxes.length-1" @click="fill('quantity', 'down')">往下填充</button></div>
            </div>
            <p class="fill-hint">填充仅作用于本页；往下填充按序号应用到后续标记。</p>
            <p v-if="selectedBox.note" class="box-note">{{ selectedBox.note }}</p>
            <div class="editor-buttons"><button class="secondary" type="button" @click="startRecognition({ page_id: page.id, box_ids: [selected], mode: 'all' })"><ScanLine :size="15" />重新识别</button><button class="primary" :disabled="!selectedBox.runner || !selectedBox.part_number"><Check :size="15" />确认校对</button></div>
          </fieldset>
        </form>
        <p v-else class="inspector-footnote">点击标记可修改板件、零件号和用量。模糊结果需要人工确认。</p>
      </aside>
    </div>
    <div v-else-if="tab === 'summary' && summary" class="summary-pane">
      <header class="summary-heading"><div><h2>装配前，把零件准备好。</h2><p>同一部件、同一板件合并展示，重复编号的数量自动累加。</p></div><span class="summary-total"><b>{{ summary.total_quantity }}</b>件 / {{ summary.part_kinds }}种零件</span></header>
      <p v-if="summary.unresolved" class="notice warning">还有 {{ summary.unresolved }} 个标记待识别或复核，未计入下方汇总。导出文件的「识别明细」会保留全部记录。</p>
      <p v-else class="summary-note"><CheckCheck :size="17" />全部已创建标记均已处理。请继续核对说明书中是否漏框，以及左右对称、重复装配的实际用量。</p>
      <div class="summary-mode" role="group" aria-label="汇总方式"><button class="secondary" :aria-pressed="summaryMode === 'category'" @click="summaryMode = 'category'">按部件汇总</button><button class="secondary" :aria-pressed="summaryMode === 'runner'" @click="summaryMode = 'runner'">按板件汇总</button></div>
      <p class="summary-explanation">{{ summaryMode === 'category' ? '与网页版一致：相同部件分类、相同板件的零件放在同一行，方便按装配部位取件。' : '跨部件分类合并同一板件，方便一次剪齐这块板件上需要的零件。' }}每个编号后均显示「× 数量」。</p>
      <div class="table-scroll"><table class="grouped-summary"><caption class="sr-only">{{ task.title }}的{{ summaryMode === 'category' ? '按部件汇总' : '按板件汇总' }}</caption><thead><tr><th v-if="summaryMode === 'category'" scope="col">部件分类</th><th scope="col">板件</th><th scope="col">零件号 × 数量</th><th scope="col">合计数量</th><th v-if="summaryMode === 'runner'" scope="col">涉及部件分类</th><th scope="col">来源页码</th></tr></thead><tbody><tr v-for="(row, i) in summaryRows" :key="summaryMode + i"><td v-if="summaryMode === 'category'">{{ row.category }}</td><td class="mono"><span class="runner-tag">{{ row.runner }}</span></td><td class="summary-parts-cell"><div class="summary-parts"><span v-for="part in row.parts" :key="part.part_number" class="summary-part mono">{{ part.part_number }}<span> × {{ part.quantity }}</span></span></div></td><td class="mono summary-quantity">{{ row.quantity }}<span> 件</span></td><td v-if="summaryMode === 'runner'">{{ row.categories.join('、') }}</td><td>{{ row.pages.join('、') }}</td></tr><tr v-if="!summaryRows.length"><td colspan="5" class="table-empty">还没有可汇总的零件。先回到说明书标注，识别或手动填写板件和编号。</td></tr></tbody><tfoot v-if="summaryRows.length"><tr><td colspan="5">合计 {{ summary.total_quantity }} 件 · {{ summary.part_kinds }} 种零件 · {{ summary.by_runner.length }} 块板件</td></tr></tfoot></table></div>
    </div>
    <div v-else class="loading-panel" role="status"><LoaderCircle :size="24" class="spin" />正在准备工作台…</div>
    <Dialog v-if="dialog === 'recognize'" title="批量识别" @close="dialog = ''"><p class="dialog-intro">每 10 个截图按序号从上到下拼成一张图，再提交一次识别；不足 10 个也会提交。拼图将发送到已配置的模型服务，可能产生 API 费用。已校对内容默认保留。最多同时运行 2 个识别任务，更多任务自动排队；其他页面可继续编辑。</p><div class="choice-list"><button @click="startRecognition({ mode: 'pending' })"><ScanLine :size="21" /><span><strong>识别整份说明书的未完成项</strong><small>包括待识别、待复核与失败的标记，自动跳过已在队列中的页面</small></span></button><button :disabled="!!pageJob" @click="startRecognition({ page_id: page.id, mode: 'review' })"><Focus :size="21" /><span><strong>重试本页待复核与失败项</strong><small>保留其他识别结果</small></span></button><button :disabled="!!pageJob" @click="dialog = 'rerun'"><Undo2 :size="21" /><span><strong>重新识别本页所有标记</strong><small>将覆盖本页已有识别结果和人工编号</small></span></button></div></Dialog>
    <Dialog v-if="dialog === 'rerun'" title="重新识别本页？" @close="dialog = ''"><p class="dialog-intro">本页 {{ page.boxes.length }} 个标记将重新请求模型，已有板件和零件号会被识别结果覆盖，分类和数量保留。</p><footer class="dialog-actions"><button class="secondary" @click="dialog = ''">取消</button><button class="primary" @click="startRecognition({ page_id: page.id, mode: 'all' })">确认重新识别</button></footer></Dialog>
    <Dialog v-if="dialog === 'crop' && selectedBox" :title="`标记 ${selectedIndex+1} · 截图对照`" wide @close="dialog = ''"><img class="crop-expanded" :src="detailSource" alt="放大的标记截图"><p class="dialog-intro">板件：{{ selectedBox.runner || '未填写' }} · 零件号：{{ selectedBox.part_number || '未填写' }}</p></Dialog>
    <Dialog v-if="dialog === 'confirm-page'" title="确认本页校对完成" @close="dialog = ''"><p class="dialog-intro">请核对本页所有装配步骤，确认没有遗漏标记，分类、板件、零件号和数量准确。左右对称与重复装配的数量也需要核对。</p><label v-if="!page.boxes.length" class="field">本页没有取件内容的原因<input v-model="noPartsReason" maxlength="200" placeholder="例如：封面、目录、工具说明"></label><p v-if="error" class="notice error" role="alert">{{ error }}</p><footer class="dialog-actions"><button class="secondary" @click="dialog = ''">返回核对</button><button class="primary" :disabled="busy || (!page.boxes.length && !noPartsReason.trim())" @click="confirmPage">确认本页完成</button></footer></Dialog>
    <ShareDialog v-if="dialog === 'share'" :task-id="taskId" @close="dialog = ''" />
    <input ref="imageFiles" class="sr-only" type="file" :accept="imageAccept" multiple aria-label="追加说明书图片" @change="appendImages">
  </section>
</template>
<style scoped>
.completion-strip{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:4px 20px;background:#f0f5ef;border-bottom:1px solid #dce5d9;font-size:12px;flex-shrink:0}
.summary-mode{display:flex;gap:8px;flex-wrap:wrap;margin-top:22px}.summary-mode button{min-height:44px}.summary-mode button[aria-pressed="true"]{background:var(--accent);border-color:var(--accent);color:white}.summary-explanation{font-size:12px;color:var(--muted);line-height:1.8;margin:12px 0 16px}.grouped-summary{min-width:640px}.grouped-summary th{white-space:nowrap}.summary-parts-cell{width:45%;min-width:220px}.summary-parts{display:flex;flex-wrap:wrap;gap:8px}.summary-part{display:inline-flex;align-items:center;gap:3px;padding:6px 9px;background:var(--accent-soft);border-radius:5px;color:var(--accent);white-space:nowrap;font-weight:600}.summary-part>span{font-weight:400}.summary-quantity{white-space:nowrap;font-weight:600}.summary-quantity>span{font-family:inherit;font-size:11px;font-weight:400;color:var(--muted)}.grouped-summary tfoot td{font-size:12px;font-weight:600;background:#f4f8f5;color:var(--accent)}
</style>
