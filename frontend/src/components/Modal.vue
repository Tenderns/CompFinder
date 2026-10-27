<script setup lang="ts">
import { onMounted, ref } from 'vue'
import Icon from './Icon.vue'
defineProps<{ title: string; wide?: boolean; full?: boolean; busy?: boolean }>()
const emit = defineEmits<{ close: [] }>()
const element = ref<HTMLDialogElement>()
onMounted(() => element.value?.showModal())
</script>
<template>
  <dialog ref="element" class="modal" :class="{ wide, full }" :aria-label="title" @cancel.prevent="!busy && emit('close')" @click="event => { if (event.target === element && !busy) emit('close') }">
    <header class="modal-header"><h2 class="truncate"><slot name="title">{{ title }}</slot></h2><div class="modal-tools"><slot name="actions" /><button class="icon-button" aria-label="关闭弹窗" :disabled="busy" @click="emit('close')"><Icon name="close" /></button></div></header>
    <div class="modal-body"><slot /></div>
  </dialog>
</template>
