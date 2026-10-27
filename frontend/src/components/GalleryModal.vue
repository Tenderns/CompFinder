<script setup lang="ts">
import { computed, ref } from 'vue'
import type { Photo, StyleInfo } from '../api'
import Icon from './Icon.vue'
import Modal from './Modal.vue'
import InfoPanel from './InfoPanel.vue'
// `info` is only passed for library styles; previews of a single image set inside the editor omit it.
const props = defineProps<{ title: string; images: Photo[]; initial?: number; searchable?: boolean; info?: StyleInfo }>()
defineEmits<{ close: []; search: [Photo]; edit: [] }>()
const index = ref(props.initial || 0)
const zoomed = ref(false)
const failed = ref(false)
const current = computed(() => props.images[index.value])
function select(n: number) { index.value = n; zoomed.value = false; failed.value = false }
function step(n: number) { if (props.images.length > 1) select((index.value + n + props.images.length) % props.images.length) }
function key(event: KeyboardEvent) {
  if (event.key === 'ArrowLeft') { event.preventDefault(); step(-1) }
  else if (event.key === 'ArrowRight') { event.preventDefault(); step(1) }
}
</script>
<template>
  <Modal :title="title" full @close="$emit('close')" @keydown="key">
    <template #actions><button v-if="searchable && current" class="button small" @click="$emit('search', current)"><Icon name="search" :size="16" />用这张图搜索</button></template>
    <div class="viewer-layout"><div class="viewer">
      <div class="viewer-stage" :class="{ zoomed }"><p v-if="failed" class="muted">图片加载失败，请关闭后重新打开。</p><img v-else-if="current" :src="current.url" :alt="`${title} 第 ${index + 1} 张`" @click="zoomed = !zoomed" @error="failed = true" /><p v-else class="muted">暂无图片</p>
        <button v-if="images.length > 1" class="stage-nav prev" aria-label="上一张" @click="step(-1)"><Icon name="left" /></button><button v-if="images.length > 1" class="stage-nav next" aria-label="下一张" @click="step(1)"><Icon name="right" /></button>
      </div>
      <div class="viewer-bar"><span class="muted">{{ images.length ? index + 1 : 0 }} / {{ images.length }}<span class="hint-keys"> · ← → 切换</span></span><button class="button small ghost" @click="zoomed = !zoomed"><Icon name="zoom" :size="16" />{{ zoomed ? '适合窗口' : '查看原图' }}</button></div>
      <div v-if="images.length > 1" class="thumb-strip"><button v-for="(photo, i) in images" :key="photo.id" :class="{ active: index === i }" :aria-label="`查看第 ${i + 1} 张`" @click="select(i)"><img :src="photo.thumbnailUrl" :alt="`缩略图 ${i + 1}`" /></button></div>
    </div><InfoPanel v-if="info" :info="info" @edit="$emit('edit')" /></div>
  </Modal>
</template>
