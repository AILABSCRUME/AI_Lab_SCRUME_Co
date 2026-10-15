/**
 * polza-limit — прогресс-бар суточного лимита Polza.ai в строке управления
 * композера, слева от выбора модели (composer.actions рендерится ровно перед
 * пилюлей модели). Один чип = ОДИН ключ владельца: тот, что вписан в корневой
 * .env агента.
 *
 * Цифры достаются локальным скриптом (scripts/polza-limits.cmd →
 * polza_limits.py): он опрашивает /v1/key, /v1/balance и /v1/history/generations
 * по этому ключу, складывает стоимость генераций за местные сутки и группирует
 * их по моделям. Ключ остаётся в .env, в рендерер не попадает: плагин вызывает
 * готовый .cmd через gateway RPC shell.exec (путь проверен модулем approval —
 * без -c/-e, не dangerous).
 *
 * Наведение открывает подсказку с карточкой: полоса лимита,
 * разбитая по моделям, легенда с суммами и долями, цифры по лимиту и кошельку.
 * Клик — обновление.
 *
 * ОГРАНИЧЕНИЯ shell.exec: только хвост stdout (4000 символов) и 30 с. Скрипт
 * печатает компактный JSON (~800 символов, ~3 с), опрос идёт раз в 5 минут.
 */

import { COMPOSER_AREAS, cn, haptic, host, queryClient, Tip, useQuery, useValue } from '@hermes/plugin-sdk'
import { jsx, jsxs } from 'react/jsx-runtime'

const ID = 'polza-limit'

// Путь через %LOCALAPPDATA%: shell.exec выполняет команду через cmd.exe, а он
// раскрывает переменную у каждого пользователя. Хардкод C:\\Users\\Admin на чужой
// машине не нашёлся бы. Пробелов в пути нет — кавычки не нужны.
const CMD =
  '%LOCALAPPDATA%\\hermes\\.polza-limits\\polza-limits.cmd'

const QUERY_KEY = [ID, 'usage']
const REFRESH_MS = 300_000

/**
 * Цвета моделей: тема даёт всего несколько акцентов, а моделей в сутках 5-8,
 * поэтому палитра задана явно. «Другое» всегда серое.
 */
const PALETTE = ['#8B7CF6', '#4EA8DE', '#3FB950', '#D29922', '#F85149', '#DB61A2', '#39C5CF']

function colorFor(index, name) {
  return name === 'Другое' ? 'var(--ui-text-quaternary)' : PALETTE[index % PALETTE.length]
}

/** Разбор stdout скрипта: JSON от первой «{» в последней непустой строке. */
function parsePayload(raw) {
  const text = String(raw || '').trim()
  const line = text.split('\n').map(s => s.trim()).filter(Boolean).pop() || ''
  const cut = line.indexOf('{')

  if (cut < 0) {
    throw new Error(line.slice(0, 120) || 'пустой вывод скрипта')
  }

  let data

  try {
    data = JSON.parse(line.slice(cut))
  } catch {
    throw new Error('ответ обрезан (лимит shell.exec — 4000 символов)')
  }

  if (data.ok === false) {
    throw new Error(data.error || 'скрипт вернул ошибку')
  }

  if (!Array.isArray(data.k) || data.k.length === 0) {
    throw new Error('в ответе нет массива ключей k')
  }

  return data
}

async function fetchUsage() {
  const res = await host.request('shell.exec', { command: CMD }, 45_000)

  if (res && res.blocked) {
    throw new Error(res.hint || 'shell.exec заблокирован')
  }

  if (!res || res.code !== 0) {
    const err = String((res && res.stderr) || '').trim()
    throw new Error(err.slice(0, 160) || `скрипт вернул код ${res ? res.code : '?'}`)
  }

  return parsePayload(res.stdout)
}

function money(v) {
  return Number(v).toFixed(2)
}

/** Цвет всей полосы по заполнению: <30% зелёный, 30–75% акцент, ≥75% красный. */
function toneFor(pct) {
  if (pct === null) {
    return 'var(--ui-text-quaternary)'
  }

  if (pct >= 75) {
    return 'var(--ui-red)'
  }

  if (pct >= 30) {
    return 'var(--ui-accent)'
  }

  return 'var(--ui-green)'
}

/** «Модель \x1f рубли \x1f запросы» → объект с цветом. */
function parseModels(rows) {
  return (rows || []).map((row, i) => {
    const [name, cost, count] = String(row).split('\u001f')

    return {
      name,
      cost: Number(cost) || 0,
      count: Number(count) || 0,
      color: colorFor(i, name)
    }
  })
}

/** Процент суточного лимита ключа; null — лимит не задан (или нет данных). */
function limitPct(k) {
  const lim = Number(k.limit) || 0

  if (!lim) {
    return null
  }

  return Math.max(0, Math.min(100, (Number(k.used) / lim) * 100))
}

/** Короткая подпись ключа в чипе: «default + local» → «default». */
function shortKey(label) {
  return String(label || '').split(/[\s+]+/)[0]
}

/** Карточка ОДНОГО ключа: полоса лимита по моделям, легенда, цифры. */
function KeyCard({ k }) {
  const models = parseModels(k.m)
  const totalLimit = Number(k.limit) || 0
  const used = Number(k.used) || 0
  const pct = totalLimit > 0 ? Math.max(0, Math.min(100, (used / totalLimit) * 100)) : 0
  const modelsSum = models.reduce((acc, m) => acc + m.cost, 0) || 1

  return jsxs('div', {
    style: { width: '300px', display: 'flex', flexDirection: 'column', gap: '8px' },
    children: [
      // 1. Полоса лимита, разбитая по моделям: доля каждой — от ЛИМИТА,
      // поэтому незакрашенный хвост и есть свободный лимит.
      jsxs('div', {
        style: { display: 'flex', flexDirection: 'column', gap: '4px' },
        children: [
          jsxs('div', {
            style: { display: 'flex', justifyContent: 'space-between', fontSize: '11px' },
            children: [
              jsx('span', { children: k.p || 'ключ' }),
              jsx('span', {
                style: { color: toneFor(pct) },
                children: `${money(used)} из ${money(totalLimit)} ₽ · ${pct.toFixed(1)}%`
              })
            ]
          }),
          jsx('span', {
            style: {
              display: 'flex',
              width: '100%',
              height: '10px',
              borderRadius: '3px',
              background: 'var(--ui-stroke-secondary)',
              overflow: 'hidden'
            },
            children: models.map((m, i) =>
              jsx(
                'span',
                {
                  title: `${m.name}: ${money(m.cost)} ₽`,
                  style: {
                    display: 'block',
                    width: `${totalLimit > 0 ? (m.cost / totalLimit) * 100 : 0}%`,
                    height: '100%',
                    background: m.color
                  }
                },
                `bar-${i}-${m.name}`
              )
            )
          })
        ]
      }),
      // 2. Легенда: цвет, модель, доля от расхода, сумма, число генераций.
      jsxs('div', {
        style: { display: 'flex', flexDirection: 'column', gap: '3px', fontSize: '11px' },
        children: models.map((m, i) =>
          jsxs(
            'div',
            {
              style: { display: 'flex', alignItems: 'center', gap: '6px' },
              children: [
                jsx('span', {
                  style: {
                    width: '8px',
                    height: '8px',
                    borderRadius: '2px',
                    background: m.color,
                    flex: '0 0 auto'
                  }
                }),
                jsx('span', {
                  style: {
                    flex: '1 1 auto',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap'
                  },
                  children: m.name
                }),
                jsx('span', {
                  style: { color: 'var(--ui-text-tertiary)', fontVariantNumeric: 'tabular-nums' },
                  children: `${((m.cost / modelsSum) * 100).toFixed(1)}%`
                }),
                jsx('span', {
                  style: { fontVariantNumeric: 'tabular-nums', minWidth: '58px', textAlign: 'right' },
                  children: `${money(m.cost)} ₽`
                }),
                jsx('span', {
                  style: {
                    color: 'var(--ui-text-quaternary)',
                    fontVariantNumeric: 'tabular-nums',
                    minWidth: '32px',
                    textAlign: 'right'
                  },
                  children: `${m.count}`
                })
              ]
            },
            `row-${i}-${m.name}`
          )
        )
      }),
      // 3. Прежние цифры по ключу.
      jsxs('div', {
        style: {
          borderTop: '1px solid var(--ui-stroke-secondary)',
          paddingTop: '6px',
          display: 'flex',
          flexDirection: 'column',
          gap: '1px',
          fontSize: '11px',
          color: 'var(--ui-text-tertiary)'
        },
        children: [
          jsx('div', {
            children: `${k.gen || 0} генераций за сутки · сброс лимита: ${k.reset || 'daily'}`
          }),
          jsx('div', { children: `остаток лимита ${money(k.left)} ₽` }),
          jsx('div', {
            children: `кошелёк ${money(k.amount)} ₽ · доступно ${money(k.avail)} ₽`
          }),
          jsx('div', { children: `неделя ${money(k.week)} ₽` })
        ]
      })
    ]
  })
}

/** Подсказка: карточка на каждый ключ + шапка и строка подсказки. */
function UsageCard({ data }) {
  const keys = Array.isArray(data.k) ? data.k : []

  return jsxs('div', {
    style: { width: '300px', display: 'flex', flexDirection: 'column', gap: '12px' },
    children: [
      jsxs('div', {
        style: { display: 'flex', justifyContent: 'space-between', fontSize: '11px' },
        children: [
          jsx('span', { children: 'Polza.ai · суточный лимит' }),
          jsx('span', { style: { color: 'var(--ui-text-quaternary)' }, children: data.day || '' })
        ]
      }),
      keys.map((k, i) =>
        jsx(
          'div',
          {
            style: {
              display: 'flex',
              flexDirection: 'column',
              gap: '8px',
              borderTop: i === 0 ? 'none' : '1px solid var(--ui-stroke-secondary)',
              paddingTop: i === 0 ? '0' : '10px'
            },
            children: k.err
              ? jsx('div', { style: { fontSize: '11px', color: 'var(--ui-red)' }, children: `${k.p}: ${k.err}` })
              : jsx(KeyCard, { k })
          },
          `key-${i}-${k.p}`
        )
      ),
      jsx('div', {
        style: { fontSize: '11px', color: 'var(--ui-text-quaternary)', borderTop: '1px solid var(--ui-stroke-secondary)', paddingTop: '6px' },
        children: 'клик — обновить'
      })
    ]
  })
}

/** Один ключ в чипе: микрополоса + «имя процент». */
function KeyMini({ k }) {
  const pct = limitPct(k)
  const tone = toneFor(pct)
  // Ключ один: в чипе достаточно процента; без лимита — прочерк, а не второе «Polza».
  const label = Number(k.limit) ? `${Math.round(pct)}%` : '—'

  return jsx('span', {
    title: Number(k.limit)
      ? `Polza.ai: ${money(k.used)} из ${money(k.limit)} ₽ за сутки`
      : 'Polza.ai: суточный лимит не задан на ключе',
    style: { display: 'inline-flex', alignItems: 'center', gap: '4px' },
    children: [
      jsx('span', {
        style: {
          display: 'inline-block',
          width: '22px',
          height: '4px',
          borderRadius: '2px',
          background: 'var(--ui-stroke-secondary)',
          overflow: 'hidden'
        },
        children: jsx('span', {
          style: {
            display: 'block',
            width: `${pct === null ? 100 : pct}%`,
            height: '100%',
            borderRadius: '2px',
            background: tone
          }
        })
      }),
      jsx('span', {
        style: { color: tone, fontVariantNumeric: 'tabular-nums' },
        children: label
      })
    ]
  }, `keymini-${k.p}`)
}

function PolzaChip() {
  const gateway = useValue(host.state.gateway)
  const connected = Boolean(gateway)

  const { data, error, isError } = useQuery({
    queryKey: [...QUERY_KEY, connected],
    enabled: connected,
    queryFn: fetchUsage,
    refetchInterval: REFRESH_MS,
    staleTime: 60_000,
    retry: false
  })

  const keys = data && Array.isArray(data.k) ? data.k : []

  const tip = data
    ? jsx(UsageCard, { data })
    : isError
      ? `Polza.ai: нет данных — ${String(error && error.message ? error.message : error).slice(0, 240)}`
      : connected
        ? 'Polza.ai: загрузка…'
        : 'Polza.ai: шлюз не подключён'

  return jsx(Tip, {
    label: tip,
    placement: 'control',
    // Тема приложения вместо инверсного фона по умолчанию: карточке нужен
    // обычный surface, иначе палитра моделей читается на вывернутом цвете.
    className:
      'border border-(--ui-stroke-secondary) bg-(--ui-bg-elevated) text-foreground backdrop-blur-md',
    children: jsxs('button', {
      type: 'button',
      className: cn(
        'inline-flex h-(--composer-control-size) shrink-0 items-center gap-1.5 rounded-md px-1.5 text-xs transition-colors',
        'text-(--ui-text-tertiary) hover:bg-(--chrome-action-hover) hover:text-foreground'
      ),
      onClick: () => {
        haptic('tap')
        queryClient.invalidateQueries({ queryKey: QUERY_KEY })
      },
      children: [
        jsx('span', {
          style: { color: 'var(--ui-text-quaternary)', fontSize: '10px', lineHeight: '1' },
          children: 'Polza'
        }),
        ...keys.map((k, i) => jsx(KeyMini, { k }, `mini-${i}-${k.p}`)),
        keys.length
          ? null
          : jsx('span', {
              style: { color: 'var(--ui-text-quaternary)', fontSize: '10px' },
              children: isError ? '!' : '…'
            })
      ]
    })
  })
}

export default {
  id: ID,
  name: 'Polza limit',
  defaultEnabled: true,
  register(ctx) {
    // composer.actions рендерится внутри строки контролов, до ModelPill —
    // то есть визуально левее выбора модели. В статус-баре чипа больше нет.
    ctx.register({
      id: 'chip',
      area: COMPOSER_AREAS.actions,
      order: 10,
      render: () => jsx(PolzaChip, {})
    })
  }
}
