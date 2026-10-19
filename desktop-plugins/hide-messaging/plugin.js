/**
 * hide-messaging — убирает строку «Сообщения» из боковой навигации.
 *
 * Зачем: у получателя мессенджеры не подключены. Вкладка «Сообщения» — это настройка
 * Telegram, Slack, Discord и прочего, плюс шлюз сообщений: место, куда лезть не надо
 * и где легко запутаться. Убираем с глаз, не ломая саму возможность.
 *
 * Как: штатный механизм навигации — область `sidebarNav.prefs`. Ядро само применяет
 * вклад при отрисовке (`app/chat/sidebar/index.tsx`: `applySidebarNavPrefs(...)`),
 * поэтому пересборка приложения НЕ нужна. Выключишь плагин — строка вернётся сама.
 *
 * Границы, проверенные по коду:
 *   - `capabilities` скрыть НЕЛЬЗЯ (в `store/sidebar-nav.ts` есть
 *     `NEVER_HIDDEN = new Set(['capabilities'])`) — это единственный путь к
 *     выключению плагинов. `messaging` скрывается свободно.
 *   - Скрывается только СТРОКА навигации. Клавиша `nav.messaging`, пункт в палитре
 *     команд и прямой адрес `/messaging` продолжают работать — это осознанно:
 *     «убрать с глаз», а не отобрать возможность.
 */

import { SIDEBAR_NAV_PREFS_AREA } from '@hermes/plugin-sdk'

const ID = 'hide-messaging'

// Id строки из core-набора навигации (SidebarNavId в store/sidebar-nav.ts):
// 'new-session' | 'capabilities' | 'messaging' | 'artifacts' | 'cron'.
const HIDDEN_ROWS = ['messaging']

export default {
  id: ID,
  name: 'Скрыть вкладку «Сообщения»',
  defaultEnabled: true,
  register(ctx) {
    // Вклад без render: это ДАННЫЕ (preference), а не интерфейс. Ядро читает
    // `data.hide` и вычитает перечисленные id из списка строк.
    ctx.register({
      id: 'prefs',
      area: SIDEBAR_NAV_PREFS_AREA,
      // Низкий order: применяемся рано, чтобы другие вклады с порядком строк
      // не наткнулись на уже скрытую строку.
      order: 1,
      data: { hide: HIDDEN_ROWS }
    })
  }
}
