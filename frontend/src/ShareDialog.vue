<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import Dialog from './Dialog.vue'
import { api } from './api'
const props = defineProps({ taskId: String })
const emit = defineEmits(['close'])
const state = ref(null), session = ref(null), error = ref(''), busy = ref(false)
const modelName = ref(''), complete = ref(false), account = ref(''), password = ref(''), token = ref(''), jwt = ref(false)
let timer, alive = true
const uploading = computed(() => ['packing','uploading'].includes(state.value?.job?.status))
const labels = { pending: '等待审核', approved: '审核通过 · 已奖励 5 张 AI 生成卡', rejected: '未通过审核' }
async function run(fn) { busy.value = true; error.value = ''; try { await fn() } catch (e) { error.value = e.message } finally { busy.value = false } }
async function refresh(remote = false) { state.value = await api(`/tasks/${props.taskId}/share${remote ? '?refresh=1' : ''}`) }
async function poll() {
  try { await refresh() } catch (e) { if (alive) error.value = e.message }
  if (alive && uploading.value) timer = setTimeout(poll, 1000)
}
async function login() { await run(async () => { try { session.value = await api('/platform/login', { method: 'POST', body: jwt.value ? { token: token.value } : { account: account.value, password: password.value } }); await refresh() } finally { password.value = ''; token.value = '' } }) }
async function logout() { await run(async () => { session.value = await api('/platform/logout', { method: 'POST', body: {} }); await refresh() }) }
async function submit() { await run(async () => { state.value = await api(`/tasks/${props.taskId}/share`, { method: 'POST', body: { model_name: modelName.value, all_model_complete: complete.value } }); clearTimeout(timer); timer = setTimeout(poll, 700) }) }
onMounted(() => run(async () => { session.value = await api('/platform/session'); await refresh(); if (uploading.value) timer = setTimeout(poll, 1000) }))
onUnmounted(() => { alive = false; clearTimeout(timer) })
</script>
<template>
  <Dialog title="分享到取件表广场" wide @close="emit('close')">
    <p class="share-reward"><strong>审核通过奖励 5 张 AI 生成卡</strong><span>提交后等待平台审核，通过后公开展示，奖励自动发放到提交账号。</span></p>
    <p class="dialog-intro">分享包含每页说明书图片、画框位置、区域截图和零件识别结果。请核对整个模型的全部装配步骤，并确认有权分享这些说明书内容。</p>
    <div v-if="state" class="share-check">
      <strong>逐页校对 {{ state.confirmed }} / {{ state.total }}</strong>
      <p v-if="state.pending_pages.length">请返回工作台确认第 {{ state.pending_pages.join('、') }} 页；无零件的页面也需注明原因。</p>
      <p v-if="state.running">请等待所有识别任务结束。</p><p v-if="!state.box_count">至少需要一个完整的零件标记。</p>
      <p v-if="state.ready">全部页面已确认。页面修改或重新识别后，需要重新确认。</p>
    </div>
    <form v-if="session && !session.user" class="share-login" @submit.prevent="login">
      <h3>登录线上平台</h3><p>使用 agamaship.com 的账号；登录仅在本次运行有效。</p>
      <template v-if="!jwt"><label class="field">手机号 / 邮箱 / 账号<input v-model="account" autocomplete="username" required maxlength="160"></label><label class="field">登录密码<input v-model="password" type="password" autocomplete="current-password" required maxlength="256"></label></template>
      <label v-else class="field">平台 JWT<input v-model="token" type="password" autocomplete="off" required maxlength="8192" placeholder="填写线上平台签发的登录 JWT"></label>
      <div class="share-controls"><button class="primary" :disabled="busy || uploading">{{ busy ? '正在验证…' : '登录平台' }}</button><button class="text-btn" type="button" :disabled="busy || uploading" @click="jwt = !jwt; password = ''; token = ''">{{ jwt ? '使用账号密码' : '使用平台 JWT' }}</button><a href="https://agamaship.com/login" target="_blank" rel="noopener noreferrer">注册 / 设置密码</a></div>
    </form>
    <div v-else-if="session?.user" class="share-controls"><span>已登录：{{ session.user.name || '平台用户' }}（{{ session.user.id }}）</span><button class="text-btn" :disabled="busy || uploading" @click="logout">退出登录</button></div>
    <form class="share-form" @submit.prevent="submit">
      <label class="field">模型名称<input v-model="modelName" required maxlength="120" placeholder="例如：万代 MG 1/100 RX-78-2 高达 Ver.3.0" :disabled="uploading"></label>
      <label class="share-consent"><input v-model="complete" type="checkbox" :disabled="uploading">我已完成整个模型的取件表，核对了所有页面、漏框和重复装配数量，并同意分享到广场。</label>
      <p v-if="state?.job?.message" role="status">{{ state.job.message }}</p>
      <div v-if="state?.receipt" class="share-check"><strong>{{ labels[state.receipt.status] }}</strong><p>{{ state.receipt.model_name }} · 提交编号 {{ state.receipt.id }}</p><p v-if="state.receipt.review_note">审核意见：{{ state.receipt.review_note }}</p><a v-if="state.receipt.post_id" :href="`https://agamaship.com/square/${state.receipt.post_id}`" target="_blank" rel="noopener noreferrer">查看广场分享</a><button class="text-btn" type="button" :disabled="busy || uploading" @click="run(() => refresh(true))">刷新审核状态</button></div>
      <p v-if="error" class="notice error" role="alert">{{ error }}</p>
      <footer class="dialog-actions"><button class="secondary" type="button" @click="emit('close')">{{ uploading ? '返回工作台' : '关闭' }}</button><button class="primary" :disabled="busy || uploading || !state?.ready || !session?.user || !complete || !modelName.trim()">{{ uploading ? '正在提交…' : '提交审核' }}</button></footer>
    </form>
  </Dialog>
</template>
<style scoped>
.share-reward{display:grid;gap:6px;background:#edf6ed;border:1px solid #b9d7c0;padding:16px;border-radius:10px;color:#315d42}.share-reward strong{font-size:19px}.share-reward span,.share-login p,.share-check p{font-size:13px;line-height:1.7}.share-check{background:#f4f5f2;padding:12px 16px;border-radius:8px;margin:16px 0}.share-check p{margin:5px 0}.share-login,.share-form{display:grid;gap:12px;margin-top:18px}.share-login h3,.share-login p{margin:0}.share-controls{display:flex;gap:14px;align-items:center;flex-wrap:wrap;margin:14px 0}.share-controls a{font-size:13px}.share-consent{display:flex;align-items:flex-start;gap:8px;line-height:1.6;font-size:13px}.share-consent input{margin-top:4px;flex-shrink:0}
</style>
