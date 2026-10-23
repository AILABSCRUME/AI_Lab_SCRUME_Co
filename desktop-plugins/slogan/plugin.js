/**
 * slogan — девиз рядом с номером сборки в заголовке окна.
 *
 * Зачем: строка «Работа агента ограничена только вашей фантазией» — часть
 * фирменного вида сборки, а не служебная информация. Ставится в `titleBar.left`
 * сразу ПОСЛЕ чипа сборки: реестр сортирует по возрастанию `order`, поэтому
 * меньший `order` уезжает левее, а чип сборки занимает 90.
 *
 * ПОЧЕМУ НЕ СЛЕТИТ ПРИ ОБНОВЛЕНИЯХ. Плагины грузятся из корня дома агента —
 * `<HERMES_HOME>/desktop-plugins/<id>/plugin.js` (один корень на всё приложение,
 * не на профиль). Официальное обновление работает с git-копией приложения
 * (`<HERMES_HOME>/hermes-agent/`) и файлов в `desktop-plugins/` не касается;
 * единственный шаг обновления, упоминающий плагины, сбрасывает кэш каталога
 * (`post_update.step_drop_live_plugin_catalog`), а не файлы. Поэтому правки
 * внутри копии приложения обновление затирает, а плагин — нет.
 *
 * НА УЗКОМ ОКНЕ СКРЫВАЕТСЯ. Заголовок делят кнопки окна, вкладка «Новый сеанс»
 * и чип сборки; длинный девиз на ширине ноутбука выдавит их. Поэтому текст
 * показывается только когда окно шире порога, и возвращается при растягивании.
 */

import { TITLEBAR_AREAS, cn, Tip } from '@hermes/plugin-sdk'
import { useEffect, useState } from 'react'
import { jsx } from 'react/jsx-runtime'

const ID = 'slogan'
const TEXT = 'Работа агента ограничена только вашей фантазией'

// Порог подобран по составу заголовка: ниже него девиз начинает теснить
// «Новый сеанс». Значение — ширина окна в пикселях.
const NARROW_PX = 1150

function Slogan() {
  const [wide, setWide] = useState(
    () => typeof window === 'undefined' || window.innerWidth >= NARROW_PX
  )

  useEffect(() => {
    const onResize = () => setWide(window.innerWidth >= NARROW_PX)
    onResize()
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  if (!wide) {
    return null
  }

  return jsx(Tip, {
    label: TEXT,
    placement: 'control',
    children: jsx('span', {
      // Тот же размер и цвет, что у прочих readout'ов заголовка: девиз —
      // справка, а не кнопка, и клики ловить не должен.
      className: cn(
        'inline-flex h-full select-none items-center px-1.5 text-[0.6875rem]',
        'text-(--ui-text-quaternary)'
      ),
      children: TEXT
    })
  })
}

export default {
  id: ID,
  name: 'Слоган сборки',
  defaultEnabled: true,
  register(ctx) {
    ctx.register({
      id: 'slogan',
      area: TITLEBAR_AREAS.left,
      order: 95,
      render: () => jsx(Slogan, {})
    })
  }
}
