/**
 * version-badge — номер сборки агента в заголовке окна.
 *
 * Зачем: получателю нужно видеть, какая версия у него стоит. Строка состояния
 * внизу для этого не годится — она скрыта в режиме Simple (политика
 * interface-mode.ts: `statusbarVisible` показывается только при открытом входе
 * в бесплатный тариф или мастере настройки). Слоты заголовка — ПОСТОЯННЫЕ
 * точки монтирования: их рендерят всегда, и Simple их не прячет.
 *
 * Версия берётся С ДИСКА, а не из кода: установщик пишет
 * <дом>\.ailab-install.json с полем version. Это значит, что чип не устареет —
 * обновление агента меняет файл, а плагин читает его при каждом запуске.
 * Тем же путём читается дата установки (поле installed).
 *
 * Читаем через `shell.exec` — тот же RPC, которым плагин лимитов зовёт свой
 * скрипт. Здесь нужна ОДНА строка, поэтому `cmd /c type` вместо .cmd-обёртки:
 * файл маленький, лимит в 4000 символов хвоста stdout не мешает.
 *
 * Клик не открывает ничего (история версий не нужна); подсказка показывает
 * версию, дату установки и имя исходного файла.
 */

import { TITLEBAR_AREAS, cn, host, queryClient, Tip, useQuery } from '@hermes/plugin-sdk'
import { jsx, jsxs } from 'react/jsx-runtime'

const ID = 'version-badge'
const QUERY_KEY = ['version-badge', 'installed']

// Путь через %LOCALAPPDATA%: команда идёт через cmd.exe, а он раскрывает
// переменную у каждого пользователя. Хардкод C:\Users\Admin на чужой машине не
// нашёлся бы. Пробелов в пути нет — кавычки не нужны.
const MARKER = '%LOCALAPPDATA%\\hermes\\.ailab-install.json'
const CMD = `cmd /c type "${MARKER}"`

/** Читает marker-файл и достаёт version/installed. Ошибки не бросаем наружу —
 *  чип обязан быть безобидным: нет файла, значит показываем прочерк. */
async function fetchInstall() {
  // shell.exec: params {command}, ответ {stdout, stderr, code}. Проверено на
  // живом детекторе безопасности — `type` не считается ни опасной, ни
  // запрещённой командой, поэтому RPC её пропускает.
  const res = await host.request('shell.exec', { command: CMD }, 15_000)

  if (res && res.blocked) {
    return { version: '', installed: '', source: '', error: String(res.hint || 'заблокировано') }
  }

  const out = String((res && res.stdout) || '')
  const fail = String((res && res.stderr) || '').trim()

  if (!res || res.code !== 0 || !out.trim()) {
    // Файла нет или он нечитаем. Для показа это НЕ ошибка: чип просто пуст.
    return { version: '', installed: '', source: '', error: fail.slice(0, 120) }
  }

  try {
    const data = JSON.parse(out.trim())
    return {
      version: String(data.version || ''),
      installed: String(data.installed || ''),
      source: String(data.source || ''),
      error: ''
    }
  } catch {
    return { version: '', installed: '', source: '', error: 'маркер не читается как JSON' }
  }
}

/** Дата установки как в маркере (2026-10-17T23:12:33+03:00) → 17.10.2026. */
function shortDate(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || '')

  return m ? `${m[3]}.${m[2]}.${m[1]}` : ''
}

function VersionChip() {
  const { data } = useQuery({
    queryKey: QUERY_KEY,
    queryFn: fetchInstall,
    // Версия меняется только при обновлении агента, то есть почти никогда.
    // Свежести 10 минут достаточно, лишние запуски команды не нужны.
    staleTime: 10 * 60 * 1000,
    refetchOnWindowFocus: false,
    retry: false
  })

  const version = data && data.version
  const label = version ? `AILab v${version}` : 'AILab'

  const tip = version
    ? [
        `Сборка AILab SCRUME Agent v${version}`,
        shortDate(data.installed) ? `Установлена: ${shortDate(data.installed)}` : '',
        data.source ? `Источник: ${data.source}` : ''
      ]
        .filter(Boolean)
        .join('\n')
    : 'Номер сборки не найден (нет файла .ailab-install.json рядом с домом агента).'

  return jsx(Tip, {
    label: tip,
    placement: 'control',
    className:
      'border border-(--ui-stroke-secondary) bg-(--ui-bg-elevated) text-foreground backdrop-blur-md',
    children: jsx('span', {
      // Тот же размер и цвет, что у прочих readout'ов заголовка: чип не должен
      // выглядеть чужеродно и не должен ловить клики (это справка, не кнопка).
      className: cn(
        'inline-flex h-full select-none items-center px-1.5 text-[0.6875rem]',
        'text-(--ui-text-tertiary)'
      ),
      children: label
    })
  })
}

export default {
  id: ID,
  name: 'Версия сборки',
  defaultEnabled: true,
  register(ctx) {
    // titleBar.left: слева, рядом с кнопками окна. Слот постоянный — Simple его
    // не прячет, в отличие от строки состояния.
    ctx.register({
      id: 'badge',
      area: TITLEBAR_AREAS.left,
      order: 90,
      render: () => jsx(VersionChip, {})
    })
  }
}
