/**
 * polza-models — модели Polza.ai в строке управления композером
 * (composer.actions), сразу за чипом расхода (order 15 против 10).
 *
 * ДВЕ СЕКЦИИ, и это главное в плагине.
 *
 * Прайс каталога — не то, что списывают. Проверено на своих генерациях:
 * ставка входа у openai/gpt-6.1-sol 282,18 ₽ при каталоге 118,09 (×2,39),
 * у deepseek/deepseek-v4.1-flash — 50,67 при каталоге 5,78 (×8,76), а у
 * anthropic/claude-sonnet-5.5 совпала (×1,01). Множитель гуляет от 1,01 до
 * 8,76, поэтому порядок по каталогу НЕ равен порядку по деньгам: по каталогу
 * самый дорогой Claude Sonnet 5.5, по факту — GPT-6.1 Sol.
 *
 * Отсюда разделение:
 *   * «по факту списания» — модели, которыми уже пользовались; ставка
 *     посчитана из costLines каждой генерации (clientRub / quantity);
 *   * «прайс каталога — не факт» — остальные; это ориентир для выбора,
 *     а не цена.
 *
 * Данные достаёт локальный скрипт (scripts/polza-models/polza-models.cmd →
 * polza_models.py). Ключ остаётся в .env, в рендерер не попадает.
 *
 * ОГРАНИЧЕНИЯ shell.exec: только ХВОСТ stdout (4000 символов) и 30 с.
 * Скрипт печатает от дешёвого и ужимается под бюджет сам; опрос — раз в
 * 30 минут (скрипт тянет каталог 600 КБ плюс историю генераций, ~21 с).
 */

import { COMPOSER_AREAS, cn, haptic, host, queryClient, Tip, useQuery, useValue } from '@hermes/plugin-sdk'
import { jsx, jsxs } from 'react/jsx-runtime'

const ID = 'polza-models'

// Путь через %LOCALAPPDATA%: shell.exec выполняет команду через cmd.exe, а он
// раскрывает переменную у каждого пользователя.
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

/** «источник \x1f id \x1f имя \x1f вход \x1f выход \x1f кэш \x1f запросов \x1f всего ₽».
 *
 *  Источник: «ф» — фактическая ставка из costLines, «п» — прайс каталога.
 *  Хвост (запросы, всего) добавлен позже, поэтому отсутствующее даёт нули,
 *  а не NaN: при ручной подмене одного файла из двух развёртывание разойдётся.
 */
function parseRows(rows) {
  return (rows || []).map(row => {
    const [src, id, name, pin, pout, pcache, gen, total] = String(row).split('\u001f')

    return {
      fact: src === 'ф',
      id: id || '?',
      name: name || id || '?',
      pin: Number(pin) || 0,
      pout: Number(pout) || 0,
      pcache: Number(pcache) || 0,
      gen: Number(gen) || 0,
      total: Number(total) || 0
    }
  })
}

/** «52.61» → «52,61»: каталог отдаёт точку, в русском тексте это опечатка. */
function rub(v) {
  return (Number(v) || 0).toFixed(2).replace('.', ',')
}

function LegendHead({ fact }) {
  return jsxs('div', {
    style: { display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--ui-text-quaternary)' },
    children: [
      jsx('span', { style: { flex: '1 1 auto' }, children: 'модель' }),
      jsx('span', { style: { minWidth: '50px', textAlign: 'right' }, children: 'вход' }),
      jsx('span', { style: { minWidth: '50px', textAlign: 'right' }, children: 'выход' }),
      jsx('span', { style: { minWidth: '42px', textAlign: 'right' }, children: 'кэш' }),
      fact ? jsx('span', { style: { minWidth: '40px', textAlign: 'right' }, children: 'запр' }) : null,
      fact ? jsx('span', { style: { minWidth: '58px', textAlign: 'right' }, children: '₽' }) : null
    ]
  })
}

function ModelRow({ m, index }) {
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
        style: {
          fontVariantNumeric: 'tabular-nums',
          minWidth: '50px',
          textAlign: 'right',
          color: m.fact ? 'var(--ui-text-primary, inherit)' : 'var(--ui-text-tertiary)'
        },
        children: rub(m.pin)
      }),
      jsx('span', {
        style: {
          color: 'var(--ui-text-tertiary)',
          fontVariantNumeric: 'tabular-nums',
          minWidth: '50px',
          textAlign: 'right'
        },
        children: rub(m.pout)
      }),
      jsx('span', {
        style: {
          color: 'var(--ui-text-quaternary)',
          fontVariantNumeric: 'tabular-nums',
          minWidth: '42px',
          textAlign: 'right'
        },
        children: m.pcache > 0 ? rub(m.pcache) : '—'
      }),
      m.fact
        ? jsx('span', {
            style: {
              color: 'var(--ui-text-quaternary)',
              fontVariantNumeric: 'tabular-nums',
              minWidth: '40px',
              textAlign: 'right'
            },
            children: `${m.gen}`
          })
        : null,
      m.fact
        ? jsx('span', {
            style: {
              color: 'var(--ui-text-tertiary)',
              fontVariantNumeric: 'tabular-nums',
              minWidth: '58px',
              textAlign: 'right'
            },
            children: rub(m.total)
          })
        : null
    ]
  }, `row-${index}-${m.id}`)
}

function Section({ title, note, rows, fact }) {
  if (!rows.length) {
    return null
  }

  return jsxs('div', {
    style: { display: 'flex', flexDirection: 'column', gap: '2px', fontSize: '11px' },
    children: [
      jsxs('div', {
        style: { color: 'var(--ui-text-tertiary)', fontSize: '10px', textTransform: 'uppercase' },
        children: [
          jsx('span', { children: title }),
          note
            ? jsx('span', { style: { textTransform: 'none', marginLeft: '6px' }, children: note })
            : null
        ]
      }),
      jsx(LegendHead, { fact }),
      ...rows.map((m, i) => jsx(ModelRow, { m, index: i }, `m-${i}-${m.id}`))
    ]
  })
}

function CatalogCard({ data }) {
  const all = parseRows(data.m)
  const fact = all.filter(m => m.fact)
  const list = all.filter(m => !m.fact)
  // Выборка истории ограничена дедлайном shell.exec (30 с), поэтому «всего ₽» —
  // это сумма по СОБРАННЫМ генерациям, а не полный итог за окно. Ставка от
  // размера выборки почти не зависит, а сумма — зависит, и об этом надо сказать.
  const sample = fact.reduce((acc, m) => acc + m.gen, 0)

  return jsxs('div', {
    style: { width: '400px', display: 'flex', flexDirection: 'column', gap: '8px' },
    children: [
      jsxs('div', {
        style: { display: 'flex', justifyContent: 'space-between', fontSize: '11px' },
        children: [
          jsx('span', { style: { color: 'var(--ui-text-tertiary)' }, children: 'Polza.ai · модели по цене' }),
          jsx('span', { style: { color: 'var(--ui-text-quaternary)' }, children: `${data.cur || 'RUB'} за 1 млн токенов` })
        ]
      }),
      jsx('div', {
        style: { color: 'var(--ui-text-quaternary)', fontSize: '10px' },
        children: `${data.nf} своих моделей по факту списания · ${data.nc} по прайсу каталога`
      }),
      jsx(Section, {
        title: 'по факту списания',
        note: `— costLines, списанные рубли; выборка ${sample} генераций`,
        rows: fact,
        fact: true
      }),
      jsx(Section, {
        title: 'прайс каталога — не факт',
        note: `— отличается от списания до 9 раз, показаны ${list.length} самых дешёвых`,
        rows: list,
        fact: false
      }),
      jsx('div', {
        style: { color: 'var(--ui-text-quaternary)', fontSize: '10px' },
        children: 'клик — обновить · сортировка по цене входа'
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
    // composer.actions рендерится внутри строки контролов, до ModelPill.
    // Order 15 ставит чип сразу за расходом (10): цены и трата рядом.
    ctx.register({
      id: 'chip',
      area: COMPOSER_AREAS.actions,
      order: 15,
      render: () => jsx(ModelsChip, {})
    })
  }
}
