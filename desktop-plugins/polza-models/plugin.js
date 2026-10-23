/**
 * polza-models — ранжирование моделей Polza.ai по цене в строке управления
 * композера (composer.actions), сразу за чипом расхода (order 15 против 10).
 *
 * Зачем: разброс цен в каталоге — три порядка. В одном и том же каталоге
 * 1,63 ₽ и 17 713 ₽ за миллион токенов входа. При таком разбросе выбирать
 * модель по названию нельзя: для черновой работы и для аудита нужны разные,
 * и «дороже» не значит «лучше для этой задачи».
 *
 * Цены — рублёвые и уже посчитанные: каталог отдаёт их в top_provider.pricing
 * с полем currency = RUB, пересчитывать нечего.
 *
 * Данные достаёт локальный скрипт (scripts/polza-models/polza-models.cmd →
 * polza_models.py): читает /v1/models, фильтрует чат-модели с ценой и печатает
 * их от дешёвых к дорогим. Ключ остаётся в .env, в рендерер не попадает:
 * плагин вызывает готовый .cmd через gateway RPC shell.exec.
 *
 * ОГРАНИЧЕНИЯ shell.exec: только ХВОСТ stdout (4000 символов) и 30 с. Скрипт
 * печатает от самого дешёвого и сам ужимает список под бюджет — иначе обрезка
 * съела бы именно дешёвые модели, самое ценное в этом списке. Опрос — раз в
 * 30 минут: каталог меняется редко, а запрос тянет 600 КБ.
 */

import { COMPOSER_AREAS, cn, haptic, host, queryClient, Tip, useQuery, useValue } from '@hermes/plugin-sdk'
import { jsx, jsxs } from 'react/jsx-runtime'

const ID = 'polza-models'

// Путь через %LOCALAPPDATA%: shell.exec выполняет команду через cmd.exe, а он
// раскрывает переменную у каждого пользователя. Хардкод C:\\Users\\Admin на чужой
// машине не нашёлся бы. Пробелов в пути нет — кавычки не нужны.
const CMD =
  '%LOCALAPPDATA%\\hermes\\.polza-models\\polza-models.cmd'

const QUERY_KEY = [ID, 'catalog']
const REFRESH_MS = 1_800_000

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
    throw new Error(data.err || 'скрипт вернул ошибку')
  }

  if (!Array.isArray(data.m) || data.m.length === 0) {
    throw new Error('в ответе нет массива моделей m')
  }

  return data
}

async function fetchCatalog() {
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

/** «id \x1f имя \x1f вход \x1f выход \x1f кэш» → объект.
 *
 *  Хвост добавлен позже, чем первые поля: при ручной подмене одного файла из
 *  двух развёртывание может разойтись, поэтому отсутствующее обязано давать
 *  нули, а не NaN.
 */
function parseRows(rows) {
  return (rows || []).map(row => {
    const [id, name, pin, pout, pcache] = String(row).split('\u001f')

    return {
      id: id || '?',
      name: name || id || '?',
      pin: Number(pin) || 0,
      pout: Number(pout) || 0,
      pcache: Number(pcache) || 0
    }
  })
}

/** «1.63» → «1,63»: каталог отдаёт точку, читается это как опечатка. */
function rub(v, digits = 2) {
  return (Number(v) || 0).toFixed(digits).replace('.', ',')
}

/** Три порядка разброса: 17713.2 → «17,7 тыс.», 1771.32 → «1 771». */
function rubShort(v) {
  const n = Number(v) || 0

  if (n >= 10_000) {
    return `${(n / 1000).toFixed(1).replace('.', ',')} тыс.`
  }

  if (n >= 1_000) {
    return `${Math.round(n).toLocaleString('ru-RU')}`
  }

  return rub(n)
}

function LegendHead() {
  return jsxs('div', {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: '6px',
      color: 'var(--ui-text-quaternary)'
    },
    children: [
      jsx('span', { style: { flex: '1 1 auto' }, children: 'модель' }),
      jsx('span', { style: { minWidth: '52px', textAlign: 'right' }, children: 'вход' }),
      jsx('span', { style: { minWidth: '52px', textAlign: 'right' }, children: 'выход' }),
      jsx('span', { style: { minWidth: '44px', textAlign: 'right' }, children: 'кэш' })
    ]
  })
}

function ModelRow({ m, index }) {
  // Зебра вместо цвета модели: список читается сверху вниз, и полоски
  // помогают не потерять строку. Палитра тут была бы шумом.
  const bg = index % 2 ? 'transparent' : 'var(--ui-bg-secondary, transparent)'

  return jsxs('div', {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: '6px',
      background: bg,
      borderRadius: '3px',
      padding: '1px 2px'
    },
    children: [
      jsxs('span', {
        style: {
          flex: '1 1 auto',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap'
        },
        children: [
          jsx('span', { children: m.name }),
          jsx('span', {
            style: { color: 'var(--ui-text-quaternary)', marginLeft: '6px', fontSize: '10px' },
            children: m.id
          })
        ]
      }),
      jsx('span', {
        style: { fontVariantNumeric: 'tabular-nums', minWidth: '52px', textAlign: 'right' },
        children: rub(m.pin)
      }),
      jsx('span', {
        style: {
          color: 'var(--ui-text-tertiary)',
          fontVariantNumeric: 'tabular-nums',
          minWidth: '52px',
          textAlign: 'right'
        },
        children: rub(m.pout)
      }),
      jsx('span', {
        style: {
          color: 'var(--ui-text-quaternary)',
          fontVariantNumeric: 'tabular-nums',
          minWidth: '44px',
          textAlign: 'right'
        },
        children: m.pcache > 0 ? rub(m.pcache) : '—'
      })
    ]
  }, `row-${index}-${m.id}`)
}

function CatalogCard({ data }) {
  const models = parseRows(data.m)

  return jsxs('div', {
    style: { width: '380px', display: 'flex', flexDirection: 'column', gap: '8px' },
    children: [
      jsxs('div', {
        style: { display: 'flex', justifyContent: 'space-between', fontSize: '11px' },
        children: [
          jsx('span', { style: { color: 'var(--ui-text-tertiary)' }, children: 'Polza.ai · модели по цене' }),
          jsx('span', { style: { color: 'var(--ui-text-quaternary)' }, children: data.cur || 'RUB' })
        ]
      }),
      jsx('div', {
        style: { color: 'var(--ui-text-quaternary)', fontSize: '11px' },
        children: `${data.n} чат-моделей с ценой · ₽ за 1 млн токенов · от ${rub(data.min)} до ${rubShort(data.max)}`
      }),
      jsxs('div', {
        style: { display: 'flex', flexDirection: 'column', gap: '2px', fontSize: '11px' },
        children: [jsx(LegendHead, {}), ...models.map((m, i) => jsx(ModelRow, { m, index: i }, `m-${i}-${m.id}`))]
      }),
      jsx('div', {
        style: { color: 'var(--ui-text-quaternary)', fontSize: '10px' },
        children: `показаны ${models.length} самых дешёвых из ${data.n} · сортировка по входу · клик — обновить`
      })
    ]
  })
}

function ModelsChip() {
  const gateway = useValue(host.state.gateway)
  const connected = Boolean(gateway)

  const { data, error, isError } = useQuery({
    queryKey: [...QUERY_KEY, connected],
    enabled: connected,
    queryFn: fetchCatalog,
    refetchInterval: REFRESH_MS,
    staleTime: 300_000,
    retry: false
  })

  const tip = data
    ? jsx(CatalogCard, { data })
    : isError
      ? `Polza.ai: каталог недоступен — ${String(error && error.message ? error.message : error).slice(0, 240)}`
      : connected
        ? 'Polza.ai: загрузка каталога…'
        : 'Polza.ai: шлюз не подключён'

  return jsx(Tip, {
    label: tip,
    placement: 'control',
    // Тема приложения вместо инверсного фона по умолчанию: таблице цен нужен
    // обычный surface.
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
          children: 'Модели'
        }),
        data
          ? jsx('span', {
              style: { fontVariantNumeric: 'tabular-nums' },
              children: `от ${rub(data.min)}`
            })
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
  name: 'Polza models',
  defaultEnabled: true,
  register(ctx) {
    // composer.actions рендерится внутри строки контролов, до ModelPill —
    // то есть визуально левее выбора модели. Order 15 ставит чип сразу за
    // расходом (10), чтобы цены и трата читались рядом.
    ctx.register({
      id: 'chip',
      area: COMPOSER_AREAS.actions,
      order: 15,
      render: () => jsx(ModelsChip, {})
    })
  }
}
