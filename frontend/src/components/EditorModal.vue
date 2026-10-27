<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { api, emptyInfo, infoCount, infoGroups, json, imageAccept, validateFile, stateLabel, type InfoEntry, type Photo, type Role, type Style, type StyleInfo } from '../api'
import { confirmAction, fail, notify } from '../ui'
import Modal from './Modal.vue'
import Icon from './Icon.vue'
import GalleryModal from './GalleryModal.vue'
const props = defineProps<{ id: string; tab?: 'images' | 'info' }>()
const emit = defineEmits<{ close: []; changed: [] }>()
const item = ref<Style | null>(null)
const name = ref('')
const tab = ref(props.tab || 'images')
const draft = ref<StyleInfo>(emptyInfo())
const infoForm = ref<HTMLFormElement>()
const formId = `style-info-${props.id}`
const busy = ref(false)
const progress = ref('')
const problem = ref('')
const loadFailed = ref(false)
const preview = ref<{ images: Photo[]; initial: number; title: string } | null>(null)
const over = ref<Role | null>(null)
let alive = true
// Compare what the server would store: trimmed values without blank rows.
const rows = (entries: InfoEntry[]) => entries.map(r => [r.name.trim(), r.value.trim()]).filter(([n, v]) => n || v)
const normalized = (info: StyleInfo) => JSON.stringify([rows(info.params), rows(info.visual), info.notes.trim()])
const infoDirty = computed(() => !!item.value && normalized(draft.value) !== normalized(item.value.info || emptyInfo()))
const nameDirty = computed(() => !!item.value && name.value.trim() !== item.value.name)
function resetDraft() {
  const info = item.value?.info || emptyInfo()
  draft.value = { params: info.params.map(r => ({ ...r })), visual: info.visual.map(r => ({ ...r })), notes: info.notes }
}
async function load(first = false) {
  const data = await api<Style>(`/admin/styles/${props.id}`)
  if (!alive) return
  item.value = data
  if (first) { name.value = data.name; resetDraft() }
}
async function change(body: unknown) {
  busy.value = true
  try { item.value = await api<Style>(`/admin/styles/${props.id}`, json('PATCH', body)); emit('changed'); return true }
  catch (error) { fail(error); return false }
  finally { busy.value = false }
}
async function addRow(group: 'params' | 'visual') {
  draft.value[group].push({ name: '', value: '' })
  await nextTick()
  const added = infoForm.value?.querySelectorAll<HTMLElement>(`[data-group="${group}"] .kv-row`)
  added?.[added.length - 1]?.querySelector('input')?.focus()
}
async function saveInfo() {
  if (await change({ info: draft.value })) { resetDraft(); notify('款式信息已保存') }
}
async function close() {
  if ((infoDirty.value || nameDirty.value) && !await confirmAction('款式名称或款式信息有未保存的修改，关闭后会丢失。', { title: '放弃未保存的修改？', action: '放弃修改' })) return
  emit('close')
}
async function upload(role: Role, files: File[]) {
  if (!files.length || busy.value) return
  busy.value = true
  const errors: string[] = []
  let added = 0, duplicates = 0
  for (const [i, file] of files.entries()) {
    progress.value = `正在上传 ${i + 1} / ${files.length}`
    const invalid = validateFile(file)
    if (invalid) { errors.push(invalid); continue }
    const body = new FormData(); body.append('role', role); body.append('file', file)
    try { const result = await api<{ duplicate: boolean }>(`/admin/styles/${props.id}/images`, { method: 'POST', body }); result.duplicate ? duplicates++ : added++ }
    catch (error) { errors.push(`${file.name}：${error instanceof Error ? error.message : '上传失败'}`) }
  }
  try { await load(); emit('changed') } catch (error) { fail(error) }
  busy.value = false; progress.value = ''; problem.value = errors.join('\n')
  notify(`已添加 ${added} 张${duplicates ? `，跳过 ${duplicates} 张重复图片` : ''}${errors.length ? `，${errors.length} 张失败` : ''}`, errors.length > 0)
}
function selected(role: Role, event: Event) { const input = event.target as HTMLInputElement; upload(role, Array.from(input.files || [])); input.value = '' }
async function remove(photo: Photo) {
  if (!await confirmAction(`删除这张${photo.role === 'recognition' ? '识别' : '展示'}图片？${photo.role === 'recognition' ? '它将立即退出检索。' : ''}`)) return
  busy.value = true
  try { await api(`/admin/images/${photo.id}`, { method: 'DELETE' }); await load(); emit('changed') } catch (error) { fail(error) }
  finally { busy.value = false }
}
async function deleteStyle() {
  if (!await confirmAction(`删除“${item.value?.name}”及它的全部展示图和识别图？此操作不可恢复。`)) return
  busy.value = true
  try { await api(`/admin/styles/${props.id}`, { method: 'DELETE' }); emit('changed'); emit('close'); notify('款式已删除') } catch (error) { fail(error) }
  finally { busy.value = false }
}
function move(index: number, offset: number) {
  const order = item.value!.displayImages!.map(p => p.id)
  const target = index + offset
  if (target < 0 || target >= order.length) return
  ;[order[index], order[target]] = [order[target]!, order[index]!]
  change({ displayOrder: order })
}
async function retry() { try { await api('/admin/index/retry', { method: 'POST' }); await load(); emit('changed') } catch (error) { fail(error) } }
async function initialLoad() {
  loadFailed.value = false
  try { await load(true) } catch (error) { loadFailed.value = true; fail(error) }
}
onMounted(initialLoad)
const timer = setInterval(() => { if (!busy.value && item.value?.pendingCount) load().then(() => emit('changed')).catch(() => {}) }, 2500)
onBeforeUnmount(() => { alive = false; clearInterval(timer) })
</script>
<template>
  <Modal title="管理款式" wide :busy="busy" @close="close">
    <div v-if="!item" class="empty-state"><p>{{ loadFailed ? '款式读取失败' : '正在读取款式…' }}</p><button v-if="loadFailed" class="button" @click="initialLoad">重试</button></div>
    <template v-else><form class="name-form" @submit.prevent="change({ name: name.trim() })"><label>款式名称<input v-model="name" maxlength="120" required :disabled="busy" /></label><button class="button" :disabled="busy || !name.trim() || name === item.name">保存名称</button><span class="badge" :class="item.state">{{ stateLabel[item.state || 'draft'] }}</span></form>
      <div class="editor-tabs" role="tablist" aria-label="编辑内容"><button type="button" role="tab" :aria-selected="tab === 'images'" :class="{ active: tab === 'images' }" @click="tab = 'images'"><Icon name="image" :size="16" />图片集<span class="count">{{ item.displayCount + (item.recognitionCount || 0) }}</span></button><button type="button" role="tab" :aria-selected="tab === 'info'" :class="{ active: tab === 'info' }" @click="tab = 'info'"><Icon name="info" :size="16" />款式信息<span v-if="infoCount(item.info)" class="count">{{ infoCount(item.info) }}</span><span v-if="infoDirty" class="dirty-dot" title="有未保存的修改" /></button></div>
      <template v-if="tab === 'images'"><div v-if="item.missing?.length" class="info-banner">{{ item.missing.join('、') }}，补齐两套图片并完成索引后可参与搜索。</div>
      <div v-if="progress" class="info-banner"><span class="spinner" />{{ progress }}</div>
      <div v-if="problem" class="error-banner multiline">{{ problem }}</div>
      <div class="collection-columns"><section v-for="role in (['display', 'recognition'] as const)" :key="role" class="collection-section" :class="role">
        <div class="collection-heading"><span class="collection-symbol"><Icon :name="role === 'display' ? 'image' : 'scan'" :size="22" /></span><div><h3>{{ role === 'display' ? '展示图片集' : '识别图片集' }} <span class="count">{{ role === 'display' ? item.displayCount : item.recognitionCount }}</span></h3><p>{{ role === 'display' ? '用于搜索结果和款式详情' : '仅供引擎匹配 · 只在管理页可见' }}</p></div></div>
        <div class="collection-photos"><article v-for="(photo, i) in (role === 'display' ? item.displayImages : item.recognitionImages)" :key="photo.id" class="managed-photo"><button class="photo-preview" :aria-label="`预览${photo.filename}`" @click="preview = { images: (role === 'display' ? item.displayImages : item.recognitionImages)!, initial: i, title: role === 'display' ? '展示图片集' : '识别图片集（管理预览）' }"><img :src="photo.thumbnailUrl" :alt="photo.filename" /><span v-if="item.cover?.id === photo.id" class="cover-label">封面</span></button><p class="photo-filename" :title="photo.filename">{{ photo.filename }}</p><div v-if="role === 'recognition'" class="photo-status" :class="photo.state" :title="photo.error || ''">{{ stateLabel[photo.state || 'pending'] }}<small v-if="photo.error">{{ photo.error }}</small></div><div class="photo-actions"><template v-if="role === 'display'"><button :disabled="busy || item.cover?.id === photo.id" title="设为封面" @click="change({ coverId: photo.id })">封面</button><button :disabled="busy || i === 0" aria-label="展示图前移" @click="move(i, -1)"><Icon name="left" :size="14" /></button><button :disabled="busy || i === item.displayCount - 1" aria-label="展示图后移" @click="move(i, 1)"><Icon name="right" :size="14" /></button></template><button class="delete-photo" :disabled="busy" :aria-label="`删除${photo.filename}`" @click="remove(photo)"><Icon name="trash" :size="15" /></button></div></article></div>
        <label class="collection-upload" :class="{ disabled: busy, over: over === role }" @dragover.prevent="over = role" @dragleave="over = null" @drop.prevent="over = null; upload(role, Array.from($event.dataTransfer?.files || []))"><input type="file" :accept="imageAccept" multiple :disabled="busy" class="sr-only" :aria-label="`上传${role === 'display' ? '展示' : '识别'}图片`" @change="selected(role, $event)" /><Icon name="plus" :size="22" /><span>{{ role === 'display' ? '添加展示图片' : '添加识别图片' }}</span><small>点击选择或拖入多张图片</small></label>
      </section></div></template>
      <form v-else :id="formId" ref="infoForm" class="info-form" @submit.prevent="saveInfo">
        <p class="muted">以下内容都可以留空。填写后会显示在搜索结果对比和图库详情中，也可以在图库里按参数查找。</p>
        <div class="info-columns"><section v-for="group in infoGroups" :key="group.key" class="info-editor" :data-group="group.key">
          <header><h3>{{ group.label }}</h3><p>{{ group.hint }}</p></header>
          <div v-for="(row, i) in draft[group.key]" :key="i" class="kv-row"><input v-model="row.name" :list="`${formId}-${group.key}`" maxlength="60" placeholder="名称" :required="!!row.value.trim()" :disabled="busy" :aria-label="`${group.label} ${i + 1} 名称`" /><input v-model="row.value" maxlength="500" placeholder="内容" :disabled="busy" :aria-label="`${group.label} ${i + 1} 内容`" /><button type="button" class="icon-button" :disabled="busy" :aria-label="`删除${group.label} ${i + 1}`" @click="draft[group.key].splice(i, 1)"><Icon name="trash" :size="16" /></button></div>
          <p v-if="!draft[group.key].length" class="kv-empty">暂无{{ group.label }}</p>
          <button type="button" class="button small ghost" :disabled="busy" @click="addRow(group.key)"><Icon name="plus" :size="15" />添加{{ group.label }}</button>
          <datalist :id="`${formId}-${group.key}`"><option v-for="hint in group.suggestions" :key="hint" :value="hint" /></datalist>
        </section></div>
        <label class="field-label">备注<textarea v-model="draft.notes" rows="3" maxlength="5000" placeholder="其他说明，可留空" :disabled="busy" /></label>
      </form>
      <footer class="editor-footer"><button class="button danger-quiet" :disabled="busy" @click="deleteStyle"><Icon name="trash" :size="16" />删除款式</button><button v-if="item.failedCount && tab === 'images'" class="button" :disabled="busy" @click="retry"><Icon name="refresh" :size="16" />重试索引</button><span class="muted">{{ tab === 'images' ? '图片变更自动保存' : infoDirty ? '有未保存的修改' : '款式信息已保存' }}</span><template v-if="tab === 'info'"><button type="button" class="button" :disabled="busy || !infoDirty" @click="resetDraft">撤销修改</button><button class="button primary" :form="formId" :disabled="busy || !infoDirty">保存信息</button></template><button class="button" :class="{ primary: tab === 'images' }" :disabled="busy" @click="close">完成</button></footer>
    </template>
  </Modal><GalleryModal v-if="preview" v-bind="preview" @close="preview = null" />
</template>
