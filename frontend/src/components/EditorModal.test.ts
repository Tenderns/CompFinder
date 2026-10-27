import { mount, flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import EditorModal from './EditorModal.vue'
import { confirmation, settleConfirm } from '../ui'

let wrapper: ReturnType<typeof mount>
const style = {
  id: 's1', name: '款式', cover: null, displayCount: 0, displayImages: [], recognitionImages: [], recognitionCount: 0,
  state: 'draft', missing: [], info: { params: [{ name: '封装', value: 'DIP-4' }], visual: [], notes: '' },
}
beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(async (_url: string, init?: RequestInit) => ({
    ok: true, json: async () => init?.method === 'PATCH' ? { ...style, info: JSON.parse(init.body as string).info } : style,
  })))
  HTMLDialogElement.prototype.showModal = vi.fn()
})
afterEach(() => { wrapper?.unmount(); vi.unstubAllGlobals(); confirmation.value = null })
const patches = () => vi.mocked(fetch).mock.calls.filter(([, init]) => init?.method === 'PATCH')

describe('style info', () => {
  it('edits and saves optional parameters and visual traits', async () => {
    wrapper = mount(EditorModal, { props: { id: 's1', tab: 'info' } })
    await flushPromises()
    expect((wrapper.find('[aria-label="参数 1 内容"]').element as HTMLInputElement).value).toBe('DIP-4')
    await wrapper.findAll('.info-editor')[1]!.find('button.ghost').trigger('click')
    await wrapper.find('[aria-label="视觉信息 1 名称"]').setValue('颜色')
    await wrapper.find('[aria-label="视觉信息 1 内容"]').setValue('红色')
    expect(wrapper.find('button[form]').attributes('disabled')).toBeUndefined()
    await wrapper.find('form.info-form').trigger('submit')
    await flushPromises()
    expect(patches()).toHaveLength(1)
    expect(JSON.parse(patches()[0]![1]!.body as string)).toEqual({
      info: { params: [{ name: '封装', value: 'DIP-4' }], visual: [{ name: '颜色', value: '红色' }], notes: '' },
    })
    expect(wrapper.find('button[form]').attributes('disabled')).toBeDefined()
  })
  it('asks before discarding unsaved changes', async () => {
    wrapper = mount(EditorModal, { props: { id: 's1', tab: 'info' } })
    await flushPromises()
    await wrapper.find('textarea').setValue('补充说明')
    await wrapper.find('[aria-label="关闭弹窗"]').trigger('click')
    expect(confirmation.value?.title).toBe('放弃未保存的修改？')
    expect(wrapper.emitted('close')).toBeUndefined()
    settleConfirm(true)
    await flushPromises()
    expect(wrapper.emitted('close')).toHaveLength(1)
  })
})
