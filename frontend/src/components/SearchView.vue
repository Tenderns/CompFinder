<script setup lang="ts">
import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from 'vue'
import { api, imageAccept, photoFile, validateFile, type Photo, type QueryPhoto, type SearchResult } from '../api'
import { fail, notify, queuedQuery } from '../ui'
import Icon from './Icon.vue'
import CropFrame from './CropFrame.vue'
import FramedImage from './FramedImage.vue'
import Modal from './Modal.vue'
import StyleCard from './StyleCard.vue'
import CompareModal from './CompareModal.vue'
const props = defineProps<{ searchableCount: number; revision?: number }>()
const emit = defineEmits<{ manage: []; edit: [string] }>()
const maxPhotos = 6
const photos = ref<QueryPhoto[]>([])
const picker = ref<HTMLInputElement>()
const cropping = ref<QueryPhoto | null>(null)
const result = ref<SearchResult | null>(null)
// Copies of the photos the current result was computed from (the compare view shows exactly these).
const searched = ref<QueryPhoto[]>([])
const busy = ref(false)
const dirty = ref(false)
const dragging = ref(false)
const comparing = ref<number | null>(null)
const cropIndex = computed(() => photos.value.findIndex(p => p.id === cropping.value?.id))
const merged = computed(() => result.value ? searched.value.length - result.value.queryCount : 0)
let request: AbortController | null = null
let timer: ReturnType<typeof setTimeout> | undefined
let serial = 0
let dragDepth = 0
let cropsBefore = new Map<string, string>()
// Removed photos keep their preview URL while the shown result still references them.
const retired: QueryPhoto[] = []

function release() {
  const used = new Set([...photos.value, ...searched.value].map(p => p.id))
  for (let i = retired.length - 1; i >= 0; i--) {
    if (!used.has(retired[i]!.id)) { URL.revokeObjectURL(retired[i]!.url); retired.splice(i, 1) }
  }
}
function changed() {
  dirty.value = true
  clearTimeout(timer)
  if (!photos.value.length) {
    request?.abort(); serial++
    busy.value = false; dirty.value = false; result.value = null; searched.value = []; comparing.value = null
    release()
  } else if (props.searchableCount) timer = setTimeout(search, 350)
}
function addFiles(files: File[]) {
  let added = 0
  for (const file of files) {
    if (photos.value.length >= maxPhotos) { notify(`一次最多添加 ${maxPhotos} 张同一物体的照片`, true); break }
    const error = validateFile(file)
    if (error) { notify(error, true); continue }
    photos.value.push({ id: crypto.randomUUID(), file, url: URL.createObjectURL(file), crop: null })
    added++
  }
  if (added) changed()
}
function selected(event: Event) { const input = event.target as HTMLInputElement; addFiles(Array.from(input.files || [])); input.value = '' }
function remove(photo: QueryPhoto) { photos.value = photos.value.filter(p => p.id !== photo.id); retired.push(photo); changed() }
function clear() { retired.push(...photos.value); photos.value = []; changed() }
async function search() {
  clearTimeout(timer)
  if (!photos.value.length) return
  request?.abort()
  const ticket = ++serial
  const controller = request = new AbortController()
  const snapshot = photos.value.map(p => ({ ...p }))
  dirty.value = false
  busy.value = true
  const body = new FormData()
  snapshot.forEach(photo => body.append('files', photo.file))
  body.append('crops', JSON.stringify(snapshot.map(p => p.crop)))
  try {
    const data = await api<SearchResult>('/search?limit=24', { method: 'POST', body, signal: controller.signal })
    if (ticket !== serial) return
    result.value = data; searched.value = snapshot; comparing.value = null
    release()
  } catch (error) {
    if (ticket === serial && !(error instanceof DOMException && error.name === 'AbortError')) { dirty.value = true; fail(error) }
  } finally { if (ticket === serial) busy.value = false }
}
async function searchPhoto(photo: Photo) {
  try { queuedQuery.value = [await photoFile(photo)] } catch (error) { fail(error) }
}

function openCrop(photo: QueryPhoto) {
  cropsBefore = new Map(photos.value.map(p => [p.id, JSON.stringify(p.crop)]))
  cropping.value = photo
}
function closeCrop() {
  cropping.value = null
  if (photos.value.some(p => cropsBefore.get(p.id) !== JSON.stringify(p.crop))) changed()
}
function cropStep(n: number) {
  const next = photos.value[(cropIndex.value + n + photos.value.length) % photos.value.length]
  if (next) cropping.value = next
}
function cropKey(event: KeyboardEvent) {
  if (event.key === 'Enter' && !(event.target as HTMLElement).closest('button')) { event.preventDefault(); closeCrop() }
  else if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') { event.preventDefault(); cropStep(event.key === 'ArrowLeft' ? -1 : 1) }
}

const modalOpen = () => !!document.querySelector('dialog[open]')
function paste(event: ClipboardEvent) {
  if (modalOpen() || (event.target as HTMLElement)?.closest('input,textarea,[contenteditable]')) return
  const files = Array.from(event.clipboardData?.files || [])
  if (files.length) { event.preventDefault(); addFiles(files) }
}
const carriesFiles = (event: DragEvent) => !!event.dataTransfer?.types.includes('Files')
function dragEnter(event: DragEvent) {
  if (!carriesFiles(event) || modalOpen()) return
  dragDepth++
  dragging.value = true
}
function dragLeave() { if (dragging.value && --dragDepth <= 0) { dragDepth = 0; dragging.value = false } }
// Always swallow file drops on this page so a missed target never navigates the tab to the image.
function dragOver(event: DragEvent) { if (carriesFiles(event)) event.preventDefault() }
function drop(event: DragEvent) {
  if (!carriesFiles(event)) return
  event.preventDefault()
  const accept = dragging.value
  dragDepth = 0; dragging.value = false
  if (accept) addFiles(Array.from(event.dataTransfer?.files || []))
}
function attach() {
  document.addEventListener('paste', paste)
  window.addEventListener('dragenter', dragEnter)
  window.addEventListener('dragleave', dragLeave)
  window.addEventListener('dragover', dragOver)
  window.addEventListener('drop', drop)
}
function detach() {
  document.removeEventListener('paste', paste)
  window.removeEventListener('dragenter', dragEnter)
  window.removeEventListener('dragleave', dragLeave)
  window.removeEventListener('dragover', dragOver)
  window.removeEventListener('drop', drop)
  dragDepth = 0; dragging.value = false
}

watch(queuedQuery, files => {
  if (!files) return
  queuedQuery.value = null
  comparing.value = null
  retired.push(...photos.value)
  photos.value = []
  addFiles(files)
  if (!photos.value.length) changed()
}, { immediate: true })
watch(() => props.searchableCount, (count, before) => { if (count && !before && photos.value.length) search() })
onMounted(attach)
onActivated(attach)
onDeactivated(detach)
onBeforeUnmount(() => {
  detach(); clearTimeout(timer); request?.abort()
  for (const photo of new Map([...photos.value, ...retired].map(p => [p.id, p])).values()) URL.revokeObjectURL(photo.url)
})
</script>
<template>
  <input ref="picker" class="sr-only" type="file" :accept="imageAccept" multiple aria-label="选择查询图片" @change="selected" />
  <section v-if="!photos.length" class="search-landing">
    <div class="landing-head"><h1>以图搜图</h1><p>上传同一物体的 1～6 个角度，在本地图库中按外观相似度查找款式。</p></div>
    <button class="dropzone hero" @click="picker?.click()">
      <span class="dropzone-icon"><Icon name="upload" :size="28" /></span>
      <strong>拖入图片，或点击选择</strong>
      <span>也可以直接 <kbd>Ctrl</kbd> + <kbd>V</kbd> 粘贴截图</span>
      <small>JPG · PNG · WebP，每张不超过 20 MB</small>
    </button>
    <div v-if="!searchableCount" class="notice"><Icon name="info" :size="18" /><span>图库中还没有可检索的款式。为款式添加展示图与识别图并完成索引后即可搜索。</span><button class="button small" @click="emit('manage')">建立图库<Icon name="arrow" :size="15" /></button></div>
    <ol v-else class="landing-steps"><li><b>1</b>添加照片，可多个角度</li><li><b>2</b>点击照片框选目标</li><li><b>3</b>点击结果对比展示图</li></ol>
  </section>
  <div v-else class="search-layout">
    <aside class="query-panel">
      <header class="panel-head"><h2>查询图片<span class="count">{{ photos.length }} / {{ maxPhotos }}</span></h2><button class="link-button" @click="clear">清空</button></header>
      <div class="query-grid">
        <article v-for="(photo, index) in photos" :key="photo.id" class="query-photo">
          <button class="query-thumb" :aria-label="`框选查询图片 ${index + 1}`" @click="openCrop(photo)"><FramedImage :src="photo.url" :alt="`查询图片 ${index + 1}`" :crop="photo.crop" /></button>
          <span class="query-index">{{ index + 1 }}</span>
          <button class="query-remove" :aria-label="`移除查询图片 ${index + 1}`" @click="remove(photo)"><Icon name="close" :size="14" /></button>
          <button class="query-crop" :class="{ active: photo.crop }" tabindex="-1" @click="openCrop(photo)"><Icon name="crop" :size="13" />{{ photo.crop ? '已框选' : '框选' }}</button>
        </article>
        <button v-if="photos.length < maxPhotos" class="query-add" @click="picker?.click()"><Icon name="plus" :size="22" /><span>添加角度</span></button>
      </div>
      <p class="panel-note"><Icon name="lock" :size="14" />查询图片只用于本次搜索，不会保存</p>
      <button class="button primary block search-submit" :disabled="busy || !searchableCount" @click="search"><span v-if="busy" class="spinner" /><Icon v-else name="search" :size="17" />{{ busy ? '正在匹配…' : result ? '重新搜索' : '搜索' }}</button>
    </aside>
    <section class="results-panel" aria-live="polite">
      <header class="results-head">
        <h2>相似款式<span v-if="result" class="count">{{ result.items.length }}</span></h2>
        <p class="muted"><template v-if="busy">正在匹配 {{ photos.length }} 张照片…</template><template v-else-if="result">{{ result.queryCount }} 张照片参与匹配<template v-if="merged">（{{ merged }} 张重复已合并）</template> · 用时 {{ (result.elapsedMs / 1000).toFixed(2) }} 秒<template v-if="dirty"> · 查询已修改</template></template></p>
      </header>
      <div v-if="!searchableCount" class="empty-state"><Icon name="layers" :size="36" /><h3>图库中还没有可检索的款式</h3><p>为款式添加展示图与识别图，索引完成后即可搜索。</p><button class="button primary" @click="emit('manage')">建立图库<Icon name="arrow" :size="16" /></button></div>
      <div v-else-if="busy && !result" class="result-grid"><div v-for="n in 8" :key="n" class="skeleton-card"><span /><i /><i /></div></div>
      <template v-else-if="result?.items.length">
        <div class="result-grid" :class="{ stale: busy || dirty }"><StyleCard v-for="(item, i) in result.items" :key="item.id" :item="item" :rank="i + 1" @open="comparing = i" /></div>
        <p class="results-note"><Icon name="info" :size="14" />{{ result.message }}。点击结果可与查询图片并排对比。</p>
      </template>
      <div v-else-if="result" class="empty-state"><Icon name="search" :size="36" /><h3>没有找到相似款式</h3><p>{{ result.message }}</p></div>
      <div v-else class="empty-state"><Icon name="search" :size="36" /><h3>准备搜索</h3><p>点击“搜索”开始匹配。</p></div>
    </section>
  </div>
  <div v-if="dragging" class="drop-overlay" aria-hidden="true"><div><Icon name="upload" :size="32" /><strong>松开以添加查询图片</strong><span>{{ photos.length }} / {{ maxPhotos }}</span></div></div>
  <Modal v-if="cropping" :title="`框选查询图片 ${cropIndex + 1}`" wide @close="closeCrop" @keydown="cropKey">
    <template #actions><span v-if="photos.length > 1" class="compare-nav"><button class="icon-button" aria-label="上一张查询图片" @click="cropStep(-1)"><Icon name="left" /></button><span class="muted">{{ cropIndex + 1 }} / {{ photos.length }}</span><button class="icon-button" aria-label="下一张查询图片" @click="cropStep(1)"><Icon name="right" /></button></span></template>
    <p class="muted">拖动框住要识别的物体，拖动框内部可移动位置；在空白处单击恢复整图识别。</p>
    <div class="crop-stage"><CropFrame :key="cropping.id" :src="cropping.url" v-model="cropping.crop" /></div>
    <footer class="modal-actions"><button class="button" :disabled="!cropping.crop" @click="cropping.crop = null">使用整图</button><button class="button primary" @click="closeCrop">完成</button></footer>
  </Modal>
  <CompareModal v-if="comparing !== null && result" :results="result.items" :index="comparing" :photos="searched" :query-index="result.queryIndex" :revision="revision || 0" @navigate="comparing = $event" @close="comparing = null" @search="searchPhoto" @edit="emit('edit', $event)" />
</template>
