<script setup>
import { computed, onMounted, ref } from 'vue'
import { ArrowUpRight, Check, ChevronRight, FilePlus2, FolderOpen, FolderSync, Globe, Images, Info, Layers2, LoaderCircle, Pencil, Plus, Search, Settings2, Trash2, Upload, X } from 'lucide-vue-next'
import { api, imageAccept, sortedFiles } from './api'
import Workspace from './Workspace.vue'
import SettingsDialog from './SettingsDialog.vue'
import Dialog from './Dialog.vue'
import AboutDialog from './AboutDialog.vue'
import { project } from './project'
const about = ref(false)
const tasks = ref([]), current = ref(''), query = ref(''), settings = ref(false), configured = ref(false), busy = ref(false), error = ref(''), notice = ref(''), dialog = ref(''), target = ref(null), title = ref('')
const file = ref(null), imageFiles = ref(null), work = ref(null)
const filtered = computed(() => tasks.value.filter(t => t.title.toLowerCase().includes(query.value.toLowerCase())))
let noticeTimer
async function refresh() { tasks.value = await api('/tasks') }
async function perform(fn) { error.value = ''; try { await fn() } catch (e) { error.value = e.message } }
function toast(message) { notice.value = message; clearTimeout(noticeTimer); noticeTimer = setTimeout(() => notice.value = '', 4500) }
async function openTask(id) { await perform(async () => { await work.value?.flush(); current.value = id }) }
async function home() { await perform(async () => { await work.value?.flush(); current.value = ''; await refresh() }) }
async function importFile(event) {
  const inputs = sortedFiles(event.target.files)
  if (!inputs.length) return
  busy.value = true
  await perform(async () => {
    await work.value?.flush()
    const data = new FormData(); inputs.forEach(input => data.append('file', input))
    const result = await api('/tasks/import', { method: 'POST', body: data })
    await refresh(); current.value = result.id; toast('说明书已导入，开始框选零件标号。')
  })
  busy.value = false; event.target.value = ''
}
async function demo() {
  busy.value = true
  await perform(async () => { const result = await api('/tasks/demo', { method: 'POST', body: {} }); await refresh(); current.value = result.id })
  busy.value = false
}
function manage(kind, task) { dialog.value = kind; target.value = task; title.value = task.title }
async function saveManage() {
  busy.value = true
  await perform(async () => {
    await api('/tasks/' + target.value.id, dialog.value === 'delete' ? { method: 'DELETE' } : { method: 'PATCH', body: { title: title.value } })
    dialog.value = ''; await refresh()
  })
  busy.value = false
}
function date(value) { return new Intl.DateTimeFormat('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(value)) }
onMounted(() => {
  perform(async () => { await refresh(); configured.value = Boolean((await api('/settings')).model) })
  const ready = () => window.pywebview?.api?.ready()
  window.addEventListener('pywebviewready', ready, { once: true })
  ready()
  window.addEventListener('liner-request-close', async () => {
    try { await work.value?.flush(); await window.pywebview.api.finish_close() }
    catch (e) { error.value = '关闭前保存失败：' + e.message }
  })
})
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <button class="brand" aria-label="Liner Parts 返回任务列表" @click="home"><span class="brand-symbol"><Layers2 :size="23" /></span><span><strong>LINER<span class="brand-light"> PARTS</span></strong><small>模型取件工作室</small></span></button>
      <button class="primary import-main" :disabled="busy" @click="file.click()"><Plus :size="18" />导入说明书</button>
      <button class="secondary import-images" :disabled="busy" @click="imageFiles.click()"><Images :size="18" />用图片新建任务</button>
      <nav aria-label="主导航"><button class="nav-item" :class="{ active: !current }" @click="home"><FolderOpen :size="18" /><span>我的任务</span><span class="nav-count">{{ tasks.length }}</span></button></nav>
      <div class="sidebar-section"><span class="eyebrow">最近打开</span><button v-for="task in tasks.slice(0, 7)" :key="task.id" class="recent-task" :class="{ active: current === task.id }" @click="openTask(task.id)"><span class="recent-dot" :class="task.status" /><span>{{ task.title }}</span><ChevronRight :size="14" /></button><p v-if="!tasks.length" class="sidebar-empty">导入说明书后，项目会保存在这里。</p></div>
      <div class="sidebar-bottom"><div class="local-note"><span class="local-dot" />项目保存在本机</div><button class="nav-item" aria-label="项目介绍与官网" title="项目介绍与官网" @click="about = true"><Info :size="18" /><span>项目介绍与官网</span></button><button class="nav-item" @click="settings = true"><Settings2 :size="18" />接口设置<span v-if="configured" class="connected"><Check :size="13" /></span></button><div class="version"><span>OPEN SOURCE</span><span>v0.1.4</span></div></div>
    </aside>
    <main class="main-area">
      <p v-if="error" role="alert" class="notice error global-error">{{ error }}<button class="icon-btn" aria-label="关闭错误提示" @click="error = ''"><X :size="18" /></button></p>
      <Workspace v-if="current" ref="work" :key="current" :task-id="current" @back="home" @updated="refresh().catch(e => error = e.message)" @settings="settings = true" @notice="toast" />
      <section v-else class="library">
        <header class="library-header"><div><span class="eyebrow">YOUR MODEL WORKBENCH</span><h1>我的取件表</h1><p>把说明书里的零件，整理成手边的清单。</p></div><button class="secondary" :disabled="busy" @click="file.click()"><FolderSync :size="17" />恢复项目</button></header>
        <div class="welcome-strip"><div class="welcome-copy"><span class="welcome-label">准备好，下一次装配。</span><h2>从说明书，到取件表。</h2><p>圈出编号，交给模型识别。<br>保留你的分类与用量，每一步都可以回头校对。</p><button class="text-btn" :disabled="busy" @click="demo">打开练习说明书 <ArrowUpRight :size="16" /></button></div><div class="runner-illustration" aria-hidden="true"><svg viewBox="0 0 390 205"><g fill="none" stroke="currentColor" stroke-width="2"><rect x="45" y="30" width="250" height="145" rx="13" /><path d="M45 102H295M118 30V175M215 30V175M118 65H145M215 138H238M77 102V77M265 102V77M167 102V129"/><rect x="60" y="50" width="35" height="27" rx="5"/><path d="M145 49H181L192 65L181 82H145Z"/><rect x="245" y="51" width="39" height="26" rx="4"/><path d="M69 125H93V154H60V136Z"/><path d="M150 129H184V157H150Z"/><rect x="238" y="122" width="43" height="34" rx="8"/></g><rect x="234" y="41" width="61" height="48" rx="5" fill="var(--accent-soft)" fill-opacity=".45" stroke="var(--accent)" stroke-dasharray="4 3"/><g fill="var(--accent)" font-family="monospace" font-size="12"><text x="253" y="35">A (12)</text><text x="57" y="23">RUNNER A</text></g><g transform="translate(275,115) rotate(-7)"><rect width="97" height="69" rx="6" fill="white" stroke="var(--border)"/><path d="M12 20H83M12 34H83M12 48H83" stroke="var(--border)"/><path d="M13 11L17 15L24 7" fill="none" stroke="var(--accent)" stroke-width="2"/><text x="34" y="14" font-size="9" fill="var(--muted)" font-family="monospace">PARTS LIST</text></g></svg></div></div>
        <section class="platform-entry" aria-label="胶佬 AI 应用平台"><Globe :size="23" aria-hidden="true" /><div><strong>胶佬 AI 应用平台 · agamaship.com</strong><p>AI 上色、极致分色、AI 生图、灵感画板、漆色卡与分享广场，让模型创作接着往下走。</p></div><a :href="project.website" target="_blank" rel="noopener noreferrer">访问官网 <ArrowUpRight :size="15" /></a><button class="text-btn" @click="about = true">项目与商用合作 <ChevronRight :size="14" /></button></section>
        <div class="library-controls"><h2>装配项目 <span class="count">{{ tasks.length }}</span></h2><button class="secondary small" :disabled="busy" @click="imageFiles.click()"><Images :size="16" />导入图片</button><label class="search-field"><Search :size="17" /><span class="sr-only">搜索任务</span><input v-model="query" placeholder="搜索任务名称"></label></div>
        <div v-if="filtered.length" class="task-grid"><article v-for="task in filtered" :key="task.id" class="task-card"><button class="task-open" @click="openTask(task.id)"><div class="task-cover"><img :src="`/api/pages/${task.pages[0].id}/image?thumb=1`" :alt="`${task.title}说明书封面`" loading="lazy"><span class="cover-format">{{ task.source_type === 'images' ? '图片' : task.source_type === 'mixed' ? 'PDF + 图片' : 'PDF' }} / {{ task.page_count }} PAGES</span><span class="task-status" :class="task.status">{{ task.status === 'ready' ? '可导出' : task.status === 'review' ? '待复核' : task.box_count ? '进行中' : '待标注' }}</span></div><div class="task-content"><h3>{{ task.title }}</h3><p>{{ task.ready_count }} / {{ task.box_count }} 个标记已处理</p><div class="task-progress"><i :style="{ width: task.box_count ? task.ready_count/task.box_count*100+'%' : '0%' }" /></div></div></button><footer><time :datetime="task.updated_at">{{ date(task.updated_at) }}</time><button class="icon-btn" :aria-label="`重命名 ${task.title}`" @click="manage('rename', task)"><Pencil :size="15" /></button><button class="icon-btn danger" :aria-label="`删除 ${task.title}`" @click="manage('delete', task)"><Trash2 :size="15" /></button></footer></article></div>
        <div v-else-if="query" class="empty-library"><Search :size="28" /><h3>没有找到这个任务</h3><p>试试更短的名称，或清空搜索。</p><button class="secondary" @click="query = ''">清空搜索</button></div>
        <div v-else class="empty-library"><div class="empty-icon"><FilePlus2 :size="30" /></div><h3>你的第一张取件表，从这里开始</h3><p>导入 PDF 或说明书图片，圈出需要的零件编号。<br>所有任务自动保存在电脑上，下次打开继续。</p><button class="primary" :disabled="busy" @click="file.click()"><Upload :size="17" />选择 PDF 或图片</button><small>支持 PDF、PNG、JPG、WebP、BMP 与 .liner · 每次最多 128 MB<br>多张图片按文件名数字顺序添加为页面，例如 1、2、10</small></div>
        <footer class="library-footer"><span>本地整理 · 自带模型 · 自由开源</span><button class="text-btn" @click="settings = true">{{ configured ? '管理模型接口' : '先配置识别接口' }} <ChevronRight :size="14" /></button></footer>
      </section>
    </main>
    <input ref="file" class="sr-only" type="file" :accept="'.pdf,.liner,' + imageAccept" multiple aria-label="选择说明书或项目文件" @change="importFile">
    <input ref="imageFiles" class="sr-only" type="file" :accept="imageAccept" multiple aria-label="选择说明书图片" @change="importFile">
    <SettingsDialog v-if="settings" @close="settings = false" @saved="configured = Boolean($event.model)" />
    <AboutDialog v-if="about" @close="about = false" />
    <Dialog v-if="dialog" :title="dialog === 'delete' ? '删除这个任务？' : '重命名任务'" @close="!busy && (dialog = '')"><form @submit.prevent="saveManage"><p v-if="dialog === 'delete'" class="dialog-intro">将删除本机保存的「{{ target.title }}」及其标注。你导入前的原始文件不受影响。需要保留进度时，请先进入任务备份项目。</p><label v-else class="field">任务名称<input v-model="title" maxlength="120" required autofocus></label><p v-if="error" role="alert" class="notice error">{{ error }}</p><footer class="dialog-actions"><button class="secondary" type="button" :disabled="busy" @click="dialog = ''">取消</button><button :class="dialog === 'delete' ? 'danger-button' : 'primary'" :disabled="busy">{{ dialog === 'delete' ? '删除任务' : '保存名称' }}</button></footer></form></Dialog>
    <div v-if="busy" class="busy-overlay" role="status"><LoaderCircle :size="27" class="spin" /><strong>正在处理文件…</strong><span>较大的说明书需要一点时间</span></div>
    <div v-if="notice" class="toast" role="status"><Check :size="18" />{{ notice }}</div>
  </div>
</template>

<style scoped>
.platform-entry{display:flex;align-items:center;gap:15px;margin-top:16px;padding:18px 21px;border:1px solid var(--border);border-radius:10px;background:var(--surface)}.platform-entry>svg{flex-shrink:0;color:var(--accent)}.platform-entry>div{flex:1;min-width:0}.platform-entry strong{font-size:13px;font-weight:600}.platform-entry p{font-size:12px;line-height:1.7;color:var(--muted);margin-top:5px}.platform-entry>a{display:inline-flex;align-items:center;gap:4px;min-height:44px;color:var(--accent);text-decoration:none;white-space:nowrap;font-size:12px;font-weight:600}.platform-entry>a:hover{text-decoration:underline}.platform-entry>a:focus-visible{outline:3px solid #6eaa96;outline-offset:3px}.platform-entry .text-btn{font-size:12px;min-height:44px;white-space:nowrap}@media(max-width:1200px){.platform-entry{flex-wrap:wrap;gap:7px 13px}.platform-entry>div{flex-basis:calc(100% - 45px)}.platform-entry>a{margin-left:36px}}@media(max-width:600px){.platform-entry{padding:15px}.platform-entry>svg{display:none}.platform-entry>a{margin-left:0}.platform-entry strong{line-height:1.6}}
</style>
