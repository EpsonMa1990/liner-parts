<script setup>
import { computed, onUnmounted, ref } from 'vue'
const props = defineProps({ page: Object, boxes: Array, selected: String, disabled: Boolean, zoom: Number, mode: String })
const emit = defineEmits(['change', 'select', 'delete'])
const surface = ref(null), gesture = ref(null), draft = ref(null), loaded = ref(false), imageError = ref(false)
const shown = computed(() => props.boxes.map(box => draft.value?.id === box.id ? draft.value : box))
function point(event) {
  const rect = surface.value.getBoundingClientRect()
  return { x: Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)), y: Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height)) }
}
function start(event, box = null, handle = '') {
  if (props.disabled || event.button !== 0 || !loaded.value) return
  event.preventDefault(); event.stopPropagation()
  if (box) emit('select', box.id)
  if (!box && props.mode !== 'draw') { emit('select', ''); return }
  const origin = point(event)
  gesture.value = { origin, box: box ? { ...box } : null, handle, pointer: event.pointerId }
  surface.value.setPointerCapture(event.pointerId)
  draft.value = box ? { ...box } : { id: crypto.randomUUID(), x: origin.x, y: origin.y, width: 0, height: 0, category: '', quantity: 1, runner: '', part_number: '', raw_text: '', note: '', status: 'pending' }
}
function move(event) {
  if (!gesture.value) return
  const { origin, box, handle } = gesture.value, p = point(event)
  if (!box) {
    draft.value = { ...draft.value, x: Math.min(origin.x, p.x), y: Math.min(origin.y, p.y), width: Math.abs(p.x - origin.x), height: Math.abs(p.y - origin.y) }
  } else if (!handle) {
    draft.value = { ...box, x: Math.max(0, Math.min(1-box.width, box.x + p.x-origin.x)), y: Math.max(0, Math.min(1-box.height, box.y+p.y-origin.y)) }
  } else {
    let x1 = box.x, y1 = box.y, x2 = box.x+box.width, y2 = box.y+box.height
    if (handle.includes('w')) x1 = Math.min(p.x, x2-.004)
    if (handle.includes('e')) x2 = Math.max(p.x, x1+.004)
    if (handle.includes('n')) y1 = Math.min(p.y, y2-.004)
    if (handle.includes('s')) y2 = Math.max(p.y, y1+.004)
    draft.value = { ...box, x: x1, y: y1, width: x2-x1, height: y2-y1 }
  }
}
function finish(event) {
  if (!gesture.value) return
  const item = draft.value, existing = gesture.value.box
  if (item.width >= .004 && item.height >= .004) {
    const changed = !existing || ['x','y','width','height'].some(k => Math.abs(item[k]-existing[k]) > .00001)
    if (changed) {
      const update = { ...item, status: 'pending', runner: '', part_number: '', raw_text: '', note: '' }
      emit('change', existing ? props.boxes.map(b => b.id === item.id ? update : b) : [...props.boxes, update])
      emit('select', item.id)
    }
  }
  if (surface.value.hasPointerCapture(event.pointerId)) surface.value.releasePointerCapture(event.pointerId)
  gesture.value = null; draft.value = null
}
function cancel() { gesture.value = null; draft.value = null }
function keyboard(event) {
  if (props.disabled) return
  if (event.key === 'Escape') { cancel(); emit('select', ''); return }
  const box = props.boxes.find(b => b.id === props.selected)
  if (!box) return
  if (event.key === 'Delete' || event.key === 'Backspace') { event.preventDefault(); emit('delete', box.id); return }
  if (!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key)) return
  event.preventDefault()
  const step = event.shiftKey ? .01 : .002
  const update = { ...box, status: 'pending', runner: '', part_number: '', raw_text: '', note: '' }
  if (event.key === 'ArrowLeft') update.x = Math.max(0, box.x-step)
  if (event.key === 'ArrowRight') update.x = Math.min(1-box.width, box.x+step)
  if (event.key === 'ArrowUp') update.y = Math.max(0, box.y-step)
  if (event.key === 'ArrowDown') update.y = Math.min(1-box.height, box.y+step)
  emit('change', props.boxes.map(b => b.id === box.id ? update : b))
}
function style(box) { return { left: box.x*100+'%', top: box.y*100+'%', width: box.width*100+'%', height: box.height*100+'%' } }
onUnmounted(cancel)
</script>

<template>
  <div class="canvas-scroll">
    <div ref="surface" class="paper" :class="{ drawing: mode === 'draw', locked: disabled }" :style="{ width: zoom+'%', aspectRatio: `${page.width} / ${page.height}` }" tabindex="0" role="group" aria-label="说明书标注区，拖动创建框，选框后可用方向键微调、Delete 删除" @pointerdown="start($event)" @pointermove="move" @pointerup="finish" @pointercancel="cancel" @keydown="keyboard">
      <img :src="`/api/pages/${page.id}/image`" alt="当前说明书页面" draggable="false" @load="loaded = true" @error="imageError = true">
      <span v-if="!loaded" class="canvas-loading">{{ imageError ? '页面加载失败，请重新打开该页。' : '正在渲染说明书…' }}</span>
      <div v-for="(box, index) in shown" :key="box.id" class="marker" :class="{ selected: selected === box.id, reviewed: ['recognized','manual'].includes(box.status) }" :style="style(box)" role="button" tabindex="0" :aria-label="`标记 ${index+1}，${box.runner || ''} ${box.part_number || '待识别'}`" @pointerdown="start($event, box)" @keydown.enter.stop="emit('select', box.id)" @focus="emit('select', box.id)">
        <span class="marker-number">{{ index+1 }}</span>
        <template v-if="selected === box.id && !disabled"><span v-for="handle in ['nw','ne','sw','se']" :key="handle" class="resize-handle" :class="handle" @pointerdown.stop="start($event, box, handle)" /></template>
      </div>
      <div v-if="draft && !gesture?.box" class="marker selected draft" :style="style(draft)" />
    </div>
  </div>
</template>
