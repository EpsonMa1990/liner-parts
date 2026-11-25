<script setup>
import { onMounted, ref } from 'vue'
import { ArrowUpRight, Check, Eye, EyeOff, LoaderCircle, RotateCcw, ShieldCheck, Unplug } from 'lucide-vue-next'
import Dialog from './Dialog.vue'
import { api } from './api'
const emit = defineEmits(['close', 'saved'])
const form = ref(null), key = ref(''), visible = ref(false), busy = ref(''), error = ref(''), message = ref(''), models = ref([])
onMounted(async () => { try { form.value = await api('/settings') } catch (e) { error.value = e.message } })
async function save() {
  form.value = await api('/settings', { method: 'PUT', body: { ...form.value, api_key: key.value } })
  key.value = ''
  emit('saved', form.value)
  return form.value
}
async function action(kind) {
  error.value = ''; message.value = ''; busy.value = kind
  try {
    const result = await save()
    if (kind === 'models') { models.value = await api('/settings/models'); message.value = `已读取 ${models.value.length} 个模型，请选择支持图片输入的模型。` }
    else if (kind === 'test') message.value = (await api('/settings/test', { method: 'POST', body: {} })).message
    else message.value = result.notice || '设置已保存。'
  } catch (e) { error.value = e.message } finally { busy.value = '' }
}
async function clearKey() {
  busy.value = 'clear'; error.value = ''
  try {
    form.value = await api('/settings', { method: 'PUT', body: { ...form.value, clear_key: true } })
    key.value = ''; message.value = '当前接口的密钥已清除。'; emit('saved', form.value)
  } catch (e) { error.value = e.message } finally { busy.value = '' }
}
</script>

<template>
  <Dialog title="接口设置" wide @close="!busy && emit('close')">
    <div class="settings-privacy"><ShieldCheck :size="20" aria-hidden="true" /><div><strong>您的大模型配置仅保存在本机电脑</strong><p>不会上传至 Agamaship 平台。识别时，选中的截图、提示词及必要的认证信息会发送至您配置的模型服务商。</p></div></div>
    <section class="settings-guide" aria-labelledby="model-guide-title"><div><h3 id="model-guide-title">建议使用火山引擎豆包模型</h3><p>在火山方舟开通支持图片理解的豆包模型，获取 API Key、接口地址和模型 ID 后，填写下方设置。</p></div><a class="secondary" href="https://www.volcengine.com/product/doubao" target="_blank" rel="noopener noreferrer">前往火山引擎<ArrowUpRight :size="16" aria-hidden="true" /></a></section>
    <form v-if="form" @submit.prevent="action('save')">
      <fieldset :disabled="!!busy">
        <label class="field">Base URL<input v-model="form.base_url" placeholder="https://example.com/v1" type="url" required spellcheck="false" @input="key = ''; form.has_key = false"><small>填写 OpenAI 兼容接口地址，可包含 /v1。切换地址后请重新填写对应密钥。</small></label>
        <label class="field">API Key <span v-if="form.has_key" class="inline-status"><Check :size="13" /> 已配置</span>
          <span class="input-action"><input v-model="key" :type="visible ? 'text' : 'password'" :placeholder="form.has_key ? '留空保留当前密钥' : '粘贴 API Key；本机免密服务可留空'" autocomplete="off" spellcheck="false"><button type="button" class="icon-btn" :aria-label="visible ? '隐藏密钥' : '显示密钥'" @click="visible = !visible"><EyeOff v-if="visible" :size="18" /><Eye v-else :size="18" /></button></span>
        </label>
        <div class="settings-key-row"><label class="checkbox-label"><input v-model="form.remember_key" type="checkbox">保存到系统凭据管理器</label><button v-if="form.has_key" class="text-btn danger" type="button" @click="clearKey">清除密钥</button></div>
        <label class="field">视觉模型名称<span class="input-action"><input v-model="form.model" list="model-options" placeholder="填写服务商提供的视觉模型 ID" spellcheck="false"><button type="button" class="secondary small" @click="action('models')">读取列表</button></span><datalist id="model-options"><option v-for="model in models" :key="model" :value="model" /></datalist><small>模型列表不标注视觉能力，请根据服务商说明选择。</small></label>
        <details class="advanced"><summary>高级设置与识别提示词</summary>
          <p class="fine-print">每批最多 10 个截图，按序号纵向拼成一张图后提交识别。不足 10 个时按实际数量拼接。</p>
          <label class="field">请求超时（秒）<input v-model.number="form.timeout" type="number" min="15" max="300" required></label>
          <label class="checkbox-label"><input v-model="form.json_mode" type="checkbox">启用接口 JSON 模式（需要服务商支持）</label>
          <label class="field">识别提示词<textarea v-model="form.prompt" :placeholder="form.default_prompt" rows="9" maxlength="20000" /><small>留空使用内置提示词。自定义时请保留 items、box_id 等输出字段。</small></label>
          <button type="button" class="text-btn" @click="form.prompt = ''"><RotateCcw :size="14" /> 使用内置提示词</button>
        </details>
      </fieldset>
      <p v-if="error" role="alert" class="notice error">{{ error }}</p><p v-if="message" role="status" class="notice success">{{ message }}</p>
      <p class="fine-print">测试会发送一张生成的 A(12) 图片，可能产生少量 API 费用。</p>
      <footer class="dialog-actions"><button type="button" class="secondary" :disabled="!!busy || !form.model" @click="action('test')"><LoaderCircle v-if="busy === 'test'" class="spin" :size="16" /><Unplug v-else :size="16" /> 测试图片识别</button><button class="primary" :disabled="!!busy"><LoaderCircle v-if="busy === 'save'" class="spin" :size="16" />保存设置</button></footer>
    </form>
    <p v-else class="notice" role="status">{{ error || '正在读取设置…' }}</p>
  </Dialog>
</template>

<style scoped>
.settings-privacy{display:flex;gap:10px;align-items:flex-start;margin:0 0 16px;color:var(--accent)}.settings-privacy>svg{flex-shrink:0;margin-top:2px}.settings-privacy strong{font-size:13px}.settings-privacy p,.settings-guide p{font-size:12px;line-height:1.75;color:var(--muted);margin:5px 0 0}.settings-guide{display:flex;align-items:center;gap:18px;padding:16px;background:var(--accent-soft);border:1px solid var(--border);border-radius:8px;margin:0 0 22px}.settings-guide h3{font-size:14px;margin:0;color:var(--ink)}.settings-guide>div{min-width:0;flex:1}.settings-guide>a{display:inline-flex;align-items:center;gap:6px;flex-shrink:0;min-height:44px;text-decoration:none;color:var(--accent);white-space:nowrap}.settings-guide>a:focus-visible{outline:3px solid #7da5df;outline-offset:3px}@media(max-width:600px){.settings-guide{align-items:flex-start;flex-direction:column;gap:12px}}
</style>
