<script setup>
import { onUnmounted, ref, watch } from 'vue'
import { pagePreview } from './preview-cache'
const props = defineProps({ page: Object, box: Object, number: Number })
const canvas = ref(null), failed = ref(false)
let generation = 0
watch([canvas, () => props.page.id, () => props.box.x, () => props.box.y, () => props.box.width, () => props.box.height], async () => {
  const stamp = ++generation
  if (!canvas.value) return
  const context = canvas.value.getContext('2d')
  context.clearRect(0, 0, 144, 96); failed.value = false
  try {
    const image = await pagePreview(props.page.id)
    if (stamp !== generation || !canvas.value) return
    const { x, y, width, height } = props.box
    const w = width * image.naturalWidth, h = height * image.naturalHeight
    const scale = Math.min(136 / w, 88 / h)
    context.fillStyle = 'white'; context.fillRect(0, 0, 144, 96)
    context.drawImage(image, x * image.naturalWidth, y * image.naturalHeight, w, h, (144-w*scale)/2, (96-h*scale)/2, w*scale, h*scale)
  } catch { if (stamp === generation) failed.value = true }
}, { flush: 'post' })
onUnmounted(() => generation++)
</script>

<template>
  <span class="crop-thumbnail"><canvas ref="canvas" width="144" height="96" role="img" :aria-label="`标记 ${number} 截图`" /><span v-if="failed" class="crop-failed">截图未载入</span></span>
</template>
