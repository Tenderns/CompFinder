<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api, json, photoFile, type IndexStatus, type Photo, type Style } from './api'
import { authRequired, confirmation, fail, notice, notify, queuedQuery, settleConfirm } from './ui'
import Icon from './components/Icon.vue'
import SearchView from './components/SearchView.vue'
import GalleryView from './components/GalleryView.vue'
import ImportView from './components/ImportView.vue'
import Modal from './components/Modal.vue'
import EditorModal from './components/EditorModal.vue'
import GalleryModal from './components/GalleryModal.vue'
import LoginView from './components/LoginView.vue'
import TokensView from './components/TokensView.vue'
type Page = 'search' | 'gallery' | 'manage' | 'import' | 'tokens'
const navigation = [{ id: 'search', label: '以图搜图', icon: 'scan' }, { id: 'gallery', label: '我的图库', icon: 'grid' }, { id: 'manage', label: '图库管理', icon: 'layers' }, { id: 'import', label: '批量导入', icon: 'folder' }, { id: 'tokens', label: 'AI 接入', icon: 'key' }] as const
const page = ref<Page>('search')
const status = ref<IndexStatus | null>(null)
const disconnected = ref(false)
const authEnabled = ref(false)
const revision = ref(0)
const editId = ref('')
const editTab = ref<'images' | 'info'>('images')
const detail = ref<Style | null>(null)
const creating = ref(false)
const newName = ref('')
const saving = ref(false)
const importer = ref<InstanceType<typeof ImportView>>()
const toastElement = ref<HTMLElement>()
watch(notice, async value => {
  if (value) { await nextTick(); toastElement.value?.showPopover?.() }
})
const engine = computed(() => {
  if (disconnected.value) return { tone: 'bad', text: '服务未连接' }
  if (!status.value) return { tone: 'idle', text: '正在连接' }
  if (!status.value.modelReady) return { tone: 'bad', text: '引擎待配置' }
  if (status.value.pending) return { tone: 'busy', text: `索引中 · 剩余 ${status.value.pending} 张` }
  return { tone: 'ok', text: '引擎就绪' }
})
function navigate(next: Page) {
  if (importer.value?.busy) { notify('文件正在导入，请等待完成后切换页面'); return }
  page.value = next; location.hash = next
}
function syncHash() {
  const name = location.hash.slice(1) as Page
  if (navigation.some(n => n.id === name)) navigate(name)
}
async function refresh() {
  if (authRequired.value) return
  try { status.value = await api<IndexStatus>('/admin/index'); disconnected.value = false }
  catch { disconnected.value = true }
}
function changed() {
  revision.value++; refresh()
  // Keep an open gallery detail in step with edits made in the editor on top of it.
  const open = detail.value
  if (open) api<Style>(`/styles/${open.id}`).then(data => { if (detail.value?.id === open.id) detail.value = data }).catch(() => {})
}
function edit(id: string, tab: 'images' | 'info' = 'images') { editTab.value = tab; editId.value = id }
async function showDetail(id: string) {
  try { detail.value = await api<Style>(`/styles/${id}`) } catch (error) { fail(error) }
}
async function searchWith(photo: Photo) {
  try { queuedQuery.value = [await photoFile(photo)]; detail.value = null; navigate('search') } catch (error) { fail(error) }
}
async function createStyle() {
  saving.value = true
  try { const item = await api<Style>('/admin/styles', json('POST', { name: newName.value.trim() })); creating.value = false; newName.value = ''; editId.value = item.id; changed() }
  catch (error) { fail(error) } finally { saving.value = false }
}
async function logout() { await api('/auth/logout', { method: 'POST' }).catch(() => {}); location.reload() }
async function checkAuth() {
  try {
    const state = await api<{ required: boolean; authenticated: boolean }>('/auth/status')
    authEnabled.value = state.required
    if (state.required && !state.authenticated) authRequired.value = true
  } catch { /* refresh() reports an unreachable service */ }
}
async function retry() { try { await api('/admin/index/retry', { method: 'POST' }); changed() } catch (error) { fail(error) } }
onMounted(async () => { await checkAuth(); syncHash(); refresh(); window.addEventListener('hashchange', syncHash) })
const timer = setInterval(refresh, 4000)
onBeforeUnmount(() => { clearInterval(timer); window.removeEventListener('hashchange', syncHash) })
</script>
<template>
  <LoginView v-if="authRequired" />
  <template v-else>
  <header class="topbar">
    <a class="brand" href="#search" @click.prevent="navigate('search')"><span class="brand-mark"><Icon name="scan" :size="18" /></span><span class="brand-name">CompFinder</span></a>
    <nav class="tabs" aria-label="主导航"><button v-for="link in navigation" :key="link.id" class="tab" :class="{ active: page === link.id }" :aria-current="page === link.id ? 'page' : undefined" @click="navigate(link.id)"><Icon :name="link.icon" :size="18" /><span>{{ link.label }}</span><span v-if="link.id === 'gallery' && status" class="tab-count">{{ status.searchableStyles }}</span></button></nav>
    <span class="engine" :class="engine.tone" :title="status?.problem || engine.text" role="status"><span v-if="engine.tone === 'busy'" class="spinner" /><span v-else class="dot" /><span class="engine-text">{{ engine.text }}</span></span>
    <button v-if="authEnabled" class="icon-button" title="退出登录" aria-label="退出登录" @click="logout"><Icon name="logout" :size="18" /></button>
  </header>
  <main class="page" :class="`page-${page}`">
    <div v-if="disconnected" class="error-banner">暂时无法连接本地服务，请检查启动窗口。<button @click="refresh">重试连接</button></div>
    <div v-else-if="status && !status.modelReady" class="error-banner">{{ status.problem }}<button @click="retry">重新加载引擎</button></div>
    <KeepAlive include="SearchView">
      <SearchView v-if="page === 'search'" :searchable-count="status?.searchableStyles || 0" :revision="revision" @manage="navigate('manage')" @edit="edit($event, 'info')" />
      <GalleryView v-else-if="page === 'gallery' || page === 'manage'" :key="page" :admin="page === 'manage'" :revision="revision" @detail="showDetail" @edit="edit($event)" @create="creating = true" @import="navigate('import')" />
      <ImportView v-else-if="page === 'import'" ref="importer" @changed="changed" @edit="edit($event)" />
      <TokensView v-else />
    </KeepAlive>
  </main>
  <Modal v-if="creating" title="新建款式" :busy="saving" @close="creating = false"><form @submit.prevent="createStyle"><p class="muted">给这一组图片取个名称，接下来分别添加展示图和识别图。</p><label class="field-label">款式名称<input v-model="newName" maxlength="120" placeholder="例如：圆形轻触开关" autofocus required /></label><footer class="modal-actions"><button type="button" class="button" :disabled="saving" @click="creating = false">取消</button><button class="button primary" :disabled="saving || !newName.trim()">{{ saving ? '正在创建…' : '创建并添加图片' }}<Icon name="arrow" :size="17" /></button></footer></form></Modal>
  <EditorModal v-if="editId" :id="editId" :key="editId" :tab="editTab" @close="editId = ''" @changed="changed" />
  <GalleryModal v-if="detail" :title="detail.name" :images="detail.displayImages || []" :info="detail.info" searchable @search="searchWith" @edit="edit(detail.id, 'info')" @close="detail = null" />
  <Modal v-if="confirmation" :title="confirmation.title" @close="settleConfirm(false)"><p>{{ confirmation.message }}</p><footer class="modal-actions"><button class="button" @click="settleConfirm(false)">取消</button><button class="button danger" @click="settleConfirm(true)">{{ confirmation.action }}</button></footer></Modal>
  <div v-if="notice" ref="toastElement" popover="manual" class="toast" :class="{ error: notice.error }" role="status"><Icon :name="notice.error ? 'close' : 'check'" :size="18" /><span>{{ notice.text }}</span><button aria-label="关闭提示" @click="notice = null"><Icon name="close" :size="16" /></button></div>
  </template>
</template>
