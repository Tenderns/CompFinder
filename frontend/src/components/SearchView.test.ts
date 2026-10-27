import { mount, flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import SearchView from './SearchView.vue'
import { queuedQuery } from '../ui'

let wrapper: ReturnType<typeof mount>
const result = { items: [], queryCount: 1, queryIndex: [0], elapsedMs: 5, message: '空图库' }
beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => result }))
  URL.createObjectURL = vi.fn(() => 'blob:test')
  URL.revokeObjectURL = vi.fn()
  HTMLDialogElement.prototype.showModal = vi.fn()
})
afterEach(() => { wrapper?.unmount(); vi.unstubAllGlobals(); vi.useRealTimers() })
async function add(files: File[]) {
  const input = wrapper.find('input[type=file]')
  Object.defineProperty(input.element, 'files', { configurable: true, value: files })
  await input.trigger('change')
}
const sentFiles = (call = 0) => (vi.mocked(fetch).mock.calls[call]![1]!.body as FormData)

describe('query photos', () => {
  it('submits all selected views with matching crop slots', async () => {
    wrapper = mount(SearchView, { props: { searchableCount: 1 } })
    await add([new File(['one'], 'front.png'), new File(['two'], 'side.png')])
    await wrapper.find('.search-submit').trigger('click')
    await flushPromises()
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(sentFiles().getAll('files')).toHaveLength(2)
    expect(JSON.parse(sentFiles().get('crops') as string)).toEqual([null, null])
  })
  it('searches automatically once photos settle', async () => {
    vi.useFakeTimers()
    wrapper = mount(SearchView, { props: { searchableCount: 1 } })
    await add([new File(['one'], 'front.png')])
    await add([new File(['two'], 'side.png')])
    expect(fetch).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(400)
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(sentFiles().getAll('files')).toHaveLength(2)
  })
  it('removes one view without removing the remaining view', async () => {
    wrapper = mount(SearchView, { props: { searchableCount: 1 } })
    await add([new File(['one'], 'front.png'), new File(['two'], 'side.png')])
    await wrapper.find('[aria-label="移除查询图片 1"]').trigger('click')
    expect(wrapper.findAll('.query-photo')).toHaveLength(1)
    await wrapper.find('.search-submit').trigger('click'); await flushPromises()
    expect((sentFiles().getAll('files')[0] as File).name).toBe('side.png')
  })
  it('caps input at six images and revokes previews on unmount', async () => {
    wrapper = mount(SearchView, { props: { searchableCount: 1 } })
    await add(Array.from({ length: 7 }, (_, i) => new File(['data'], `${i}.png`)))
    expect(wrapper.findAll('.query-photo')).toHaveLength(6)
    wrapper.unmount()
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(6)
  })
  it('keeps search disabled until the library has searchable styles', async () => {
    vi.useFakeTimers()
    wrapper = mount(SearchView, { props: { searchableCount: 0 } })
    await add([new File(['one'], 'front.png')])
    await vi.advanceTimersByTimeAsync(400)
    expect(fetch).not.toHaveBeenCalled()
    expect(wrapper.find('.search-submit').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('建立图库')
  })
  it('replaces the query with files handed over from the gallery', async () => {
    wrapper = mount(SearchView, { props: { searchableCount: 1 } })
    await add([new File(['one'], 'front.png'), new File(['two'], 'side.png')])
    queuedQuery.value = [new File(['lib'], '图库图片.png')]
    await flushPromises()
    expect(queuedQuery.value).toBeNull()
    expect(wrapper.findAll('.query-photo')).toHaveLength(1)
    await wrapper.find('.search-submit').trigger('click'); await flushPromises()
    expect((sentFiles().getAll('files')[0] as File).name).toBe('图库图片.png')
  })
})
