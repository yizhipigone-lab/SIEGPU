/**
 * 最近访问 + 收藏（命令面板快捷区）—— localStorage 持久化，纯前端。
 *
 * 最近访问由 router.afterEach 自动记录（首页/登录页/工作台不入最近），最多 8 条；
 * 收藏由命令面板星标切换。新手重复走同几页，这两块省去「每次重新找」的成本。
 */
export interface RecentItem {
  path: string
  title: string
}

const RECENTS_KEY = 'siegpu:recents'
const FAVS_KEY = 'siegpu:favs'

function readList(key: string): RecentItem[] {
  try {
    const v = JSON.parse(localStorage.getItem(key) || '[]')
    return Array.isArray(v) ? v : []
  } catch {
    return []
  }
}
function writeList(key: string, items: RecentItem[]): void {
  try {
    localStorage.setItem(key, JSON.stringify(items))
  } catch {
    /* 隐私模式等写入失败，忽略 */
  }
}

/** 记录一次访问：去重、置顶、最多 8 条。首页/登录页/工作台（动态路径）不入最近。 */
export function pushRecent(path: string, title: string): void {
  if (!path || path === '/' || path === '/login' || path.startsWith('/projects/')) return
  const list = readList(RECENTS_KEY).filter((r) => r.path !== path)
  list.unshift({ path, title })
  writeList(RECENTS_KEY, list.slice(0, 8))
}

export function recents(): RecentItem[] {
  return readList(RECENTS_KEY)
}

export function favs(): RecentItem[] {
  return readList(FAVS_KEY)
}

export function isFav(path: string): boolean {
  return readList(FAVS_KEY).some((f) => f.path === path)
}

export function toggleFav(item: RecentItem): void {
  const list = readList(FAVS_KEY)
  const i = list.findIndex((f) => f.path === item.path)
  if (i >= 0) list.splice(i, 1)
  else list.push(item)
  writeList(FAVS_KEY, list)
}
