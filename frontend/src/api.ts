import { authRequired } from './ui'

export type Role = 'display' | 'recognition'
export interface Photo {
  id: string; url: string; thumbnailUrl: string; width: number; height: number
  role?: Role; filename?: string; state?: string; error?: string | null
}
export interface Style {
  id: string; name: string; cover: Photo | null; displayCount: number; displayImages?: Photo[]
  recognitionImages?: Photo[]; recognitionCount?: number; indexedCount?: number
  pendingCount?: number; failedCount?: number; state?: string; missing?: string[]; searchable?: boolean
  similarity?: number; scores?: number[]; info?: StyleInfo
}
export interface InfoEntry { name: string; value: string }
export interface StyleInfo { params: InfoEntry[]; visual: InfoEntry[]; notes: string }
export interface IndexStatus {
  modelReady: boolean; problem: string | null; styles: number; searchableStyles: number
  displayImages: number; recognitionImages: number; indexed: number; pending: number; failed: number
}
export interface SearchResult { items: Style[]; queryCount: number; queryIndex: number[]; elapsedMs: number; message: string }
export interface Crop { x: number; y: number; width: number; height: number }
export interface QueryPhoto { id: string; file: File; url: string; crop: Crop | null }
export interface ImportGroup { name: string; displayCount: number; recognitionCount: number; skip: boolean; info: StyleInfo | null }
export interface ImportPreview { groups: ImportGroup[]; rejected: { path: string; message: string }[] }
export interface ImportFile { path: string; styleId: string | null; styleName: string; role: Role | 'info' | null; state: string; message: string | null }
export interface McpTool { name: string; title: string; description: string; group: string; writes: boolean }
export interface McpToken { id: string; name: string; secret: string; tools: string[]; enabled: boolean; createdAt: string; lastUsedAt: string | null }
export interface ImportJob { id: string; state: string; createdAt: string; total: number; counts: Record<string, number>; files?: ImportFile[] }

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api${path}`, options)
  if (!response.ok) {
    if (response.status === 401) authRequired.value = true
    const body = await response.json().catch(() => null)
    const detail = body?.detail
    throw new Error(typeof detail === 'string' ? detail : response.status === 422 ? '提交内容无效，请检查后重试' : `请求失败（${response.status}）`)
  }
  return response.json()
}

export function json(method: string, body: unknown): RequestInit {
  return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
}

export const imageAccept = '.jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp'
const maxBytes = 20 * 1024 * 1024
export function validateFile(file: File): string | null {
  if (!/\.(jpe?g|png|webp)$/i.test(file.name) && !['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) return `${file.name}：仅支持 JPG、PNG、WebP`
  if (file.size > maxBytes) return `${file.name}：超过 20 MB`
  if (!file.size) return `${file.name}：文件为空`
  return null
}

// Library originals are stored as lossless PNG and may exceed the upload limit; fall back to the thumbnail then.
export async function photoFile(photo: Photo): Promise<File> {
  for (const [url, name] of [[photo.url, '图库图片.png'], [photo.thumbnailUrl, '图库图片.webp']] as const) {
    const response = await fetch(url)
    if (!response.ok) throw new Error('图片读取失败，请重试')
    if (Number(response.headers.get('content-length')) > maxBytes) { await response.body?.cancel(); continue }
    const blob = await response.blob()
    if (blob.size <= maxBytes) return new File([blob], name, { type: blob.type })
  }
  throw new Error('图片过大，无法用于搜索')
}

export const infoGroups = [
  // Names follow the ytst tactile switch taxonomy v1.1, which the AI tools also enforce for visual traits.
  { key: 'params', label: '参数', hint: '料号、尺寸、电气参数等资料', suggestions: ['原厂料号', '制造商', '系列', '本体长度', '本体宽度', '推杆高度', '引脚间距', '操作力', '操作行程', '额定电流', '额定电压', '开关功能', '触点电路', '防护等级', '寿命次数', '工作温度范围'] },
  { key: 'visual', label: '视觉信息', hint: 'AI 识别的分类结果，按 ytst 规范 v1.1', suggestions: ['安装方式', '按压方向', '本体轮廓', '本体厚薄', '脚数', '端子样式', '端子分布', '按柄轮廓', '按柄凸起形态', '按柄颜色', '独立键帽', '键帽轮廓', '带支架', '带灯', '外壳颜色', '可见特殊结构'] },
] as const
// Optional file beside 展示图/识别图 in each style folder; same content as examples/导入示例/款式A.
export const infoFile = '款式信息.json'
export const infoSample = `{
  "参数": {
    "原厂料号": "TS-6606",
    "额定电压": "12V DC",
    "额定电流": "50mA"
  },
  "视觉信息": {
    "安装方式": "插件",
    "按压方向": "顶按",
    "本体轮廓": "方形",
    "脚数": 4,
    "端子样式": "通孔引脚",
    "按柄轮廓": "圆形",
    "按柄颜色": "黑色"
  },
  "备注": "视觉信息按 ytst 轻触开关规范 v1.1 填写；参数和备注可以不写。"
}
`
export const emptyInfo = (): StyleInfo => ({ params: [], visual: [], notes: '' })
export const infoCount = (info?: StyleInfo) => info ? info.params.length + info.visual.length + (info.notes ? 1 : 0) : 0
export const entryText = (entry: InfoEntry) => entry.value ? `${entry.name} ${entry.value}` : entry.name

export const formatScore = (score: number) => (score * 100).toFixed(1)

export const stateLabel: Record<string, string> = { draft: '待补图片', ready: '可检索', processing: '建立索引中', failed: '索引失败', pending: '排队中', display: '展示图' }
