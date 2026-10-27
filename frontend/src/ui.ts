import { ref, shallowRef } from 'vue'

// Set when the server answers 401; App shows the token login instead of the library.
export const authRequired = ref(false)

export const notice = ref<{ text: string; error: boolean } | null>(null)
let timer: ReturnType<typeof setTimeout> | undefined
export function notify(text: string, error = false) {
  clearTimeout(timer)
  notice.value = { text, error }
  timer = setTimeout(() => { notice.value = null }, error ? 10000 : 5000)
}
export function fail(error: unknown) { notify(error instanceof Error ? error.message : '操作失败，请重试', true) }
export const confirmation = shallowRef<{ message: string; title: string; action: string; resolve: (value: boolean) => void } | null>(null)
export function confirmAction(message: string, { title = '确认删除', action = '确认删除' } = {}): Promise<boolean> {
  return new Promise(resolve => { confirmation.value = { message, title, action, resolve } })
}
export function settleConfirm(value: boolean) {
  confirmation.value?.resolve(value)
  confirmation.value = null
}
// The Clipboard API needs HTTPS or localhost; plain-HTTP deployments fall back to a hidden textarea.
export async function copyText(text: string) {
  try { await navigator.clipboard.writeText(text); return } catch { /* fall through */ }
  const area = document.createElement('textarea')
  area.value = text
  area.setAttribute('readonly', '')
  area.style.position = 'fixed'
  area.style.opacity = '0'
  document.body.append(area)
  area.select()
  const copied = document.execCommand('copy')
  area.remove()
  if (!copied) throw new Error('复制失败，请手动选择后复制')
}
// Files handed to the search page from elsewhere (e.g. "用这张图搜索" in the gallery).
export const queuedQuery = shallowRef<File[] | null>(null)
