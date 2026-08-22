/**
 * client 入口：
 * - 指数条挂 conversation.composer.dock（输入框正下方居中），正常文档流；
 * - 新闻条同样挂 conversation.composer.dock（指数条下方），在对话窗口内滚动，
 *   不做 fixed 浮层，避免遮挡设置等其他 UI。
 */

import React from 'react'
import type { Context } from '@deepseek-ai/cordis'
import { QuotesBar, NewsBar } from './TickerBar.tsx'

export const name = 'dsh-live-ticker'
export const inject = ['slots']

export function apply(ctx: Context) {
  ctx.slots.inject('conversation.composer.dock', () =>
    ctx.slots.register({
      name: 'conversation.composer.dock',
      id: 'live-ticker-quotes',
      order: 10,
      label: () => 'live-ticker',
    }, () => React.createElement(QuotesBar)),
  )

  ctx.slots.inject('conversation.composer.dock', () =>
    ctx.slots.register({
      name: 'conversation.composer.dock',
      id: 'live-ticker-news',
      order: 20,
      label: () => 'live-ticker',
    }, () => React.createElement(NewsBar)),
  )
}
