<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api, formatScore, type Photo, type QueryPhoto, type Style } from '../api'
import Icon from './Icon.vue'
import Modal from './Modal.vue'
import FramedImage from './FramedImage.vue'
import InfoPanel from './InfoPanel.vue'
const props = defineProps<{ results: Style[]; index: number; photos: QueryPhoto[]; queryIndex: number[]; revision: number }>()
const emit = defineEmits<{ close: []; navigate: [number]; search: [Photo]; edit: [string] }>()
const details = new Map<string, Style>()
const detail = ref<Style | null>(null)
const failed = ref(false)
const shown = ref(0)
const query = ref(0)
const item = computed(() => props.results[props.index]!)
const images = computed(() => detail.value ? detail.value.displayImages || [] : null)
const current = computed(() => images.value?.[shown.value])
const photoScore = (i: number) => item.value.scores?.[props.queryIndex[i] ?? -1]
// Library edits (e.g. style info saved from the editor) bump the revision and drop cached details.
watch([() => item.value.id, () => props.revision], async ([id, revision], before) => {
  // Vue passes [] as the previous value on the immediate first run.
  const edited = before?.[1] !== undefined && before[1] !== revision
  if (edited) details.clear()
  else { shown.value = 0; failed.value = false }
  // While an edited style reloads, keep showing what we have instead of flashing a spinner.
  detail.value = details.get(id) ?? (edited && detail.value?.id === id ? detail.value : null)
  if (details.has(id)) return
  try {
    const data = await api<Style>(`/styles/${id}`)
    details.set(id, data)
    if (item.value.id !== id) return
    detail.value = data
    if (shown.value >= (data.displayImages?.length || 0)) shown.value = 0
  } catch { if (item.value.id === id && !detail.value) failed.value = true }
}, { immediate: true })
function step(n: number) { const count = images.value?.length || 0; if (count > 1) shown.value = (shown.value + n + count) % count }
function go(n: number) { const next = props.index + n; if (next >= 0 && next < props.results.length) emit('navigate', next) }
function key(event: KeyboardEvent) {
  const actions: Record<string, () => void> = { ArrowLeft: () => step(-1), ArrowRight: () => step(1), ArrowUp: () => go(-1), ArrowDown: () => go(1), k: () => go(-1), j: () => go(1) }
  const action = actions[event.key]
  if (action && !(event.target as HTMLElement).closest('input,textarea')) { event.preventDefault(); action() }
}
</script>
<template>
  <Modal :title="item.name" full @close="emit('close')" @keydown="key">
    <template #title><span class="compare-rank">#{{ index + 1 }}</span>{{ item.name }}<span class="compare-score">相似度 <b>{{ formatScore(item.similarity || 0) }}</b></span></template>
    <template #actions><span class="compare-nav"><button class="icon-button" :disabled="index === 0" aria-label="上一个款式" title="上一个款式（↑）" @click="go(-1)"><Icon name="up" /></button><span class="muted">{{ index + 1 }} / {{ results.length }}</span><button class="icon-button" :disabled="index === results.length - 1" aria-label="下一个款式" title="下一个款式（↓）" @click="go(1)"><Icon name="down" /></button></span></template>
    <div class="compare with-info">
      <section class="compare-pane">
        <header class="compare-head"><h3>查询图片</h3><span v-if="photoScore(query) !== undefined" class="muted">该角度得分 <b class="score-text">{{ formatScore(photoScore(query)!) }}</b></span></header>
        <div class="compare-stage"><FramedImage v-if="photos[query]" :src="photos[query]!.url" :alt="`查询图片 ${query + 1}`" :crop="photos[query]!.crop" /></div>
        <div v-if="photos.length > 1" class="thumb-strip"><button v-for="(photo, i) in photos" :key="photo.id" :class="{ active: query === i }" :aria-label="`查看查询图片 ${i + 1}`" @click="query = i"><img :src="photo.url" alt="" /><span v-if="photoScore(i) !== undefined" class="thumb-score">{{ formatScore(photoScore(i)!) }}</span></button></div>
      </section>
      <section class="compare-pane">
        <header class="compare-head"><h3>款式展示图</h3><span class="muted">{{ images ? `${images.length ? shown + 1 : 0} / ${images.length}` : '' }}</span><button v-if="current" class="button small ghost" @click="emit('search', current)"><Icon name="search" :size="15" />以此图搜索</button></header>
        <div class="compare-stage"><img v-if="current" :src="current.url" :alt="`${item.name} 第 ${shown + 1} 张`" /><p v-else-if="failed" class="muted">款式读取失败，可能已被删除或尚未准备好。</p><span v-else-if="!images" class="spinner" /><p v-else class="muted">暂无展示图</p>
          <button v-if="(images?.length || 0) > 1" class="stage-nav prev" aria-label="上一张展示图" @click="step(-1)"><Icon name="left" /></button><button v-if="(images?.length || 0) > 1" class="stage-nav next" aria-label="下一张展示图" @click="step(1)"><Icon name="right" /></button>
        </div>
        <div v-if="(images?.length || 0) > 1" class="thumb-strip"><button v-for="(photo, i) in images" :key="photo.id" :class="{ active: shown === i }" :aria-label="`查看第 ${i + 1} 张展示图`" @click="shown = i"><img :src="photo.thumbnailUrl" alt="" /></button></div>
      </section>
      <InfoPanel :info="detail?.info" :loading="!detail && !failed" @edit="emit('edit', item.id)" />
    </div>
    <p class="compare-hints"><span><kbd>←</kbd><kbd>→</kbd> 切换展示图</span><span><kbd>↑</kbd><kbd>↓</kbd> 切换款式</span><span><kbd>Esc</kbd> 关闭</span></p>
  </Modal>
</template>
