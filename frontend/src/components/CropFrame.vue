<script setup lang="ts">
import { computed, ref } from 'vue'
import type { Crop } from '../api'
const props = defineProps<{ src: string; modelValue: Crop | null }>()
const emit = defineEmits<{ 'update:modelValue': [Crop | null] }>()
const frame = ref<HTMLElement>()
const draft = ref<Crop | null>(null)
const hovering = ref(false)
const shown = computed(() => draft.value ?? props.modelValue)
const clamp = (n: number, min = 0, max = 1) => Math.max(min, Math.min(max, n))
let start: { x: number; y: number } | null = null
let moving: Crop | null = null
function point(event: PointerEvent) {
  const rect = frame.value!.getBoundingClientRect()
  return { x: clamp((event.clientX - rect.left) / rect.width), y: clamp((event.clientY - rect.top) / rect.height) }
}
function inside(p: { x: number; y: number }) {
  const c = props.modelValue
  return !!c && p.x >= c.x && p.x <= c.x + c.width && p.y >= c.y && p.y <= c.y + c.height
}
function box(event: PointerEvent): Crop {
  const p = point(event)
  if (moving) return { ...moving, x: clamp(moving.x + p.x - start!.x, 0, 1 - moving.width), y: clamp(moving.y + p.y - start!.y, 0, 1 - moving.height) }
  return { x: Math.min(start!.x, p.x), y: Math.min(start!.y, p.y), width: Math.abs(p.x - start!.x), height: Math.abs(p.y - start!.y) }
}
function down(event: PointerEvent) {
  if (event.button > 0) return
  frame.value?.setPointerCapture(event.pointerId)
  start = point(event)
  // Dragging inside the current box moves it; dragging elsewhere draws a new one.
  moving = inside(start) ? props.modelValue : null
  draft.value = moving ? { ...moving } : { ...start, width: 0, height: 0 }
}
function move(event: PointerEvent) {
  if (start) draft.value = box(event)
  else hovering.value = inside(point(event))
}
function up(event: PointerEvent) {
  if (!start) return
  const next = box(event)
  emit('update:modelValue', moving || (next.width > .02 && next.height > .02) ? next : null)
  start = null; moving = null; draft.value = null
}
function cancel() { start = null; moving = null; draft.value = null }
</script>
<template>
  <div class="crop-frame" :class="{ movable: hovering }" ref="frame" @pointerdown.prevent="down" @pointermove="move" @pointerup="up" @pointercancel="cancel" @pointerleave="hovering = false">
    <img :src="src" alt="拖动框选要识别的物体" draggable="false" />
    <div v-if="shown" class="crop-box" :style="{ left: `${shown.x * 100}%`, top: `${shown.y * 100}%`, width: `${shown.width * 100}%`, height: `${shown.height * 100}%` }"><i /><i /><i /><i /></div>
  </div>
</template>
