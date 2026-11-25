<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { X } from 'lucide-vue-next'
defineProps({ title: String, wide: Boolean })
const emit = defineEmits(['close'])
const dialog = ref(null)
const previous = document.activeElement
onMounted(() => dialog.value.showModal())
onUnmounted(() => previous?.focus?.())
</script>

<template>
  <dialog ref="dialog" class="dialog" :class="{ wide }" aria-labelledby="dialog-title" @cancel.prevent="emit('close')" @click="e => { if (e.target === dialog) emit('close') }">
    <header class="dialog-header"><h2 id="dialog-title">{{ title }}</h2><button class="icon-btn" aria-label="关闭对话框" @click="emit('close')"><X :size="20" /></button></header>
    <slot />
  </dialog>
</template>
