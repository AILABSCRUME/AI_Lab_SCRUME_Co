/**
 * session-time — счётчик времени текущей сессии в строке управления композера,
 * слева от чипа Polza.ai (composer.actions рендерится перед пилюлей модели,
 * а `order` меньше — значит левее).
 *
 * Время берётся из истинного старта сессии, а не из «прикрепления окна»:
 * RPC `session.list` отдаёт строку с `started_at` (epoch-СЕКУНДЫ), плагин
 * находит в ней сфокусированную сессию и считает разницу. Раз в минуту список
 * перезапрашивается, раз в секунду пересчитывается только цифра.
 *
 * Почему не `$sessionStartedAt`/`runtimeStartedAt`: эти атомы плагинам НЕ
 * отданы — `host.state` их не содержит (проверено по sdk/index.ts). Доступны
 * `focusedStoredSessionId`, `profile`, `focusedUsage` и прочие, но не время.
 *
 * Композер виден в ОБОИХ режимах интерфейса: SIMPLE_POLICY прячет статусбар,
 * но не строку контролов. Поэтому чип работает и в простом режиме — в отличие
 * от элемента `session-timer` в статусбаре.
 */

import { COMPOSER_AREAS, cn, host, Tip, useQuery, useValue } from '@hermes/plugin-sdk'
import { useEffect, useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

const ID = 'session-time'

const QUERY_KEY = [ID, 'sessions']
const REFRESH_MS = 60_000
const LIST_LIMIT = 50

/** `started_at` приходит в epoch-СЕКУНДАХ; миллисекундные значения не трогаем. */
function toMs(value) {
  if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0) {
    return null
  }

  return value < 1e12 ? value * 1000 : value
}

const pad = n => String(n).padStart(2, '0')

/** 1:05:32, а до часа — 5:32: короткая форма для узкого места в композере. */
function formatElapsed(ms) {
  const total = Math.max(0, Math.floor(ms / 1000))
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60

  return h ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`
}

function formatClock(ms) {
  const d = new Date(ms)

  return `${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function formatDate(ms) {
  const d = new Date(ms)

  return `${pad(d.getDate())}.${pad(d.getMonth() + 1)} ${formatClock(ms)}`
}

function findRow(rows, storedId) {
  if (!storedId) {
    return null
  }

  return (
    rows.find(row => row && (row.id === storedId || row.resolved_id === storedId)) ?? null
  )
}

function SessionTimeChip() {
  const storedId = useValue(host.state.focusedStoredSessionId)
  const profile = useValue(host.state.profile)

  const { data } = useQuery({
    queryFn: async () => host.request('session.list', { limit: LIST_LIMIT, profile }),
    queryKey: [...QUERY_KEY, profile],
    refetchInterval: REFRESH_MS,
    staleTime: REFRESH_MS
  })

  const rows = (data && data.sessions) || []
  const row = findRow(rows, storedId)
  const startedAt = toMs(row && row.started_at)

  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000)

    return () => clearInterval(timer)
  }, [])

  // Свежий черновик (сессии ещё нет) — чипа нет вовсе, а не «0:00».
  if (!startedAt) {
    return null
  }

  const elapsed = now - startedAt

  return jsx(Tip, {
    label: jsxs('div', {
      style: { display: 'flex', flexDirection: 'column', gap: '2px', fontSize: '11px', width: '190px' },
      children: [
        jsx('span', { children: row?.title || 'Текущая сессия' }),
        jsx('span', {
          style: { color: 'var(--ui-text-tertiary)' },
          children: `начата ${formatDate(startedAt)}`
        }),
        jsx('span', {
          style: { color: 'var(--ui-text-tertiary)' },
          children: `идёт ${formatElapsed(elapsed)}`
        })
      ]
    }),
    placement: 'control',
    children: jsx('span', {
      className: cn(
        'flex h-(--composer-control-size) items-center gap-1 rounded-md px-1.5 text-xs',
        'text-(--ui-text-tertiary) hover:bg-(--chrome-action-hover)'
      ),
      'data-slot': 'session-time-chip',
      style: { fontVariantNumeric: 'tabular-nums' },
      children: [
        jsx('i', { 'aria-hidden': 'true', className: 'codicon codicon-clock' }),
        jsx('span', { children: formatElapsed(elapsed) })
      ]
    })
  })
}

export default {
  id: ID,
  name: 'Session time',
  defaultEnabled: true,
  register(ctx) {
    ctx.register({
      id: 'chip',
      area: COMPOSER_AREAS.actions,
      order: 5,
      render: () => jsx(SessionTimeChip, {})
    })
  }
}
