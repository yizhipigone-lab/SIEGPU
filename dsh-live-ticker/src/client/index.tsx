/**
 * client 入口：注册 conversation.composer.dock 槽位。
 * 参照 dshmarket / dsh-i18n 的 slots.inject/register 形态。
 */

import React from 'react'
import type { Context } from '@deepseek-ai/cordis'
import { TickerBar } from './TickerBar.tsx'

export const name = 'dsh-live-ticker'
export const inject = ['slots']

export function apply(ctx: Context) {
  ctx.slots.inject('conversation.composer.dock', () =>
    ctx.slots.register({
      name: 'conversation.composer.dock',
      id: 'live-ticker',
      order: 100,
      label: () => 'live-ticker',
    }, () => React.createElement(TickerBar)),
  )
}
