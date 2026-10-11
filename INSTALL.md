# Инструкция по установке

Агент **Dionis** — профиль Hermes Agent: личный помощник. Ставится одной командой,
ключ API у каждого свой.

---

## 0. Что нужно заранее

| Что | Проверка | Если нет |
|---|---|---|
| Windows 10/11 | — | — |
| Git | `git --version` | `winget install Git.Git` |
| Hermes Agent | `hermes --version` | см. шаг 1 |
| Свой ключ Polza.ai | — | см. шаг 4 |

Данные Hermes лежат в `%LOCALAPPDATA%\hermes`. Агент встанет в
`%LOCALAPPDATA%\hermes\profiles\vasily`.

---

## 1. Поставить Hermes Agent (если ещё нет)

PowerShell (обычный, без администратора):

```powershell
iex (irm https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.ps1)
```

После установки **закрыть и открыть терминал заново** — установщик добавляет
`hermes` в PATH. Проверка:

```powershell
hermes --version
```

---

## 2. Получить доступ к репозиторию агента

Репозиторий приватный: https://github.com/AILABSCRUME/hermes-agent-vasily

Два варианта:

- **A. Доступ к репозиторию** — владелец добавляет вас в
  Settings → Collaborators. Дальше шаг 3, вариант A.
- **B. Без доступа** — владелец передаёт файл-бандл `vasily-<версия>.bundle`
  (например, `vasily-v1.0.1.bundle`). Дальше шаг 3, вариант B.

---

## 3. Установить агента

### Вариант A — из репозитория (рекомендуется, потом обновляется одной командой)

```powershell
hermes profile install github.com/AILABSCRUME/hermes-agent-vasily --alias --yes
```

### Вариант B — из файла-бандла (без доступа к репозиторию)

Положить `vasily-v1.0.0.bundle` в любую папку и выполнить:

```powershell
cd $env:USERPROFILE\Downloads
git clone vasily-v1.0.0.bundle vasily-dist
hermes profile install .\vasily-dist --yes
```

В обоих случаях в конце появится:

```
✓ Installed 'vasily' v1.0.0
  Profile path: C:\Users\<вы>\AppData\Local\hermes\profiles\vasily
  Next: copy .env.EXAMPLE to .env and fill in required keys
```

---

## 4. Вписать свой ключ Polza.ai — обязательный шаг

**Где взять ключ:** https://polza.ai/dashboard/api-keys (личный кабинет Polza.ai →
API-ключи → создать). Там же пополнить баланс — расход идёт с вашего счёта.

**Куда вписать:** файл `.env` в папке профиля. После установки рядом лежит шаблон
`.env.EXAMPLE`:

```powershell
cd $env:LOCALAPPDATA\hermes\profiles\vasily
copy .env.EXAMPLE .env
notepad .env
```

В открывшемся файле — одна строка, вписать ключ **после знака `=`, без кавычек и пробелов**:

```
HERMES_CUSTOM_POLZA_AI_API_KEY=ваш_ключ
```

Ключ в `config.yaml` **не вписывать** — там только имя переменной
(`key_env: HERMES_CUSTOM_POLZA_AI_API_KEY`). Так ключ не уедет в репозиторий и не
потеряется при обновлении.

Проверить, что Hermes видит файл:

```powershell
hermes -p vasily config env-path
```

Должен вернуться путь `...\profiles\vasily\.env`.

---

## 5. Запустить

```powershell
hermes -p vasily chat
```

Либо короткой командой, если при установке был флаг `--alias`:

```powershell
vasily chat
```

> На Windows обёртка `vasily.bat` создаётся в `C:\Users\<вы>\.local\bin`.
> Если команда `vasily` не находится — эта папка не в PATH; добавьте её либо
> пользуйтесь полной формой `hermes -p vasily chat`.

Первое сообщение для проверки: `Как тебя зовут и кому ты помогаешь?`
Ответ должен быть про Dionis и вас.

---

## 6. Что где менять под себя

| Что | Файл | Как правильно |
|---|---|---|
| Имя владельца, персона, тон | `%LOCALAPPDATA%\hermes\profiles\vasily\SOUL.md` | открыть в редакторе, править текст |
| Модель | `config.yaml` | только через `hermes -p vasily config set model.default <модель>` — правка файла руками ломает конфиг |
| Список моделей | `config.yaml` | `hermes -p vasily model` (интерактивный выбор) |
| Ключ API | `.env` | правка строки `HERMES_CUSTOM_POLZA_AI_API_KEY=` |
| Память о вас | — | набирается в чате само; чистится через `/memory` в чате |

`SOUL.md` — единственный файл, который стоит править текстом. Всё остальное — командами.

---

## 7. Обновление агента

Когда выходит новая версия (только для варианта A):

```powershell
hermes profile update vasily
```

Обновляются `SOUL.md`, `config.yaml`, `skills/`, `distribution.yaml`.
**Не трогаются:** `.env` с ключом, память, история сессий, ваши правки `config.yaml`
(сбросить его к версии из репозитория — `hermes profile update vasily --force-config`).

Посмотреть, что стоит:

```powershell
hermes profile info vasily
hermes profile list
```

---

## 8. Чего в комплекте нет — настроить самому (по желанию)

| Возможность | Команда / где |
|---|---|
| MCP-серверы (внешние инструменты) | `hermes -p vasily mcp catalog`, затем `hermes -p vasily mcp add` |
| Мессенджеры (Telegram и др.) | `hermes -p vasily gateway setup`, затем `hermes -p vasily gateway start` |
| Задачи по расписанию | `hermes -p vasily cron add` или через десктоп-приложение |
| Графическое приложение | `hermes desktop` (общее для всех профилей, профиль выбирается внутри) |

Скиллы (58 штук: Word, Excel, PDF, поиск, почта, заметки, карты, код) уже внутри —
их доустанавливать не нужно. Свой скилл добавляется командой
`hermes -p vasily skills install <источник>`.

---

## 9. Если что-то не работает

| Симптом | Причина / решение |
|---|---|
| `hermes: command not found` | терминал не перезапущен после установки Hermes |
| `Profile 'vasily' does not exist` | агент не установлен — вернуться к шагу 3 |
| Ответы вида «нет доступа к модели», 401 | ключ в `.env` пустой/с опечаткой — проверить строку и `hermes -p vasily config env-path` |
| Установка не находит репозиторий | репозиторий приватный — нет доступа (шаг 2), либо использовать вариант B |
| `vasily: команда не найдена` | `C:\Users\<вы>\.local\bin` не в PATH — использовать `hermes -p vasily chat` |
| Общий диагноз | `hermes -p vasily doctor` |
