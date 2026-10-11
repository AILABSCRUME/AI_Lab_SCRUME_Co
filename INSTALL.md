# Инструкция по установке

Агент **Dionis** — профиль Hermes Agent: личный помощник. Ключ API у каждого свой.

---

## Быстрый путь: запустить `setup.cmd`

Если вам передали папку с файлами `setup.cmd`, `setup.ps1` и `vasily-<версия>.bundle` —
просто **запустите `setup.cmd` двойным кликом**. Скрипт сам:

1. найдёт рядом файл агента;
2. снимает метку «скачано из интернета» (иначе Windows блокирует запуск);
3. при необходимости поставит Git и Hermes Agent;
4. поставит агента (при повторном запуске — обновит);
5. создаст файл ключа и откроет его в Блокноте — **ключ вписываете вы** (единственный ручной шаг);
6. проверит, что агент отвечает, и покажет команду запуска.

Windows может один раз спросить подтверждение (SmartScreen) — это нормально.
Первый запуск занимает несколько минут, окно закрывать нельзя.
Протокол установки сохраняется рядом: `setup-log.txt`.

Дальше — раздел 5 «Запустить». Остальные разделы нужны, только если что-то пошло не так
или вы ставите агента вручную.

---

## 0. Что нужно заранее

| Что | Проверка | Если нет |
|---|---|---|
| Windows 10/11 | — | — |
| Git | `git --version` | `winget install Git.Git` |
| Hermes Agent | `hermes --version` | см. шаг 1 |
| Свой ключ Polza.ai | — | см. шаг 4 |
| Файл агента `vasily-*.bundle` | — | получить у владельца (шаг 2) |

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

## 2. Что вам передаёт владелец

Один файл: **`vasily-<версия>.bundle`** (например `vasily-v1.0.1.bundle`).
Внутри — весь агент с историей версий. Больше ничего не нужно, доступ к репозиторию
не требуется.

---

## 3. Установить агента

Положить файл, например, в `Downloads`, открыть PowerShell:

```powershell
cd $env:USERPROFILE\Downloads
git clone vasily-v1.0.1.bundle vasily-dist
hermes profile install .\vasily-dist --yes
```

В конце появится:

```
✓ Installed 'vasily' v1.0.1
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

Первое сообщение для проверки: `Как тебя зовут и кому ты помогаешь?`
Ответ должен быть про Dionis и вас.

Короткая команда `vasily chat` вместо длинной — по желанию:

```powershell
hermes profile alias vasily        # создаёт C:\Users\<вы>\.local\bin\vasily.bat
vasily chat
```

> На Windows обёртка кладётся в `C:\Users\<вы>\.local\bin`, а этой папки нет в PATH —
> в новом терминале команда `vasily` не найдётся. Либо добавьте папку в PATH, либо
> пользуйтесь полной формой `hermes -p vasily chat`.

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

**Автоматически:** положить новый `vasily-<новая версия>.bundle` в ту же папку, где лежит
`setup.cmd`, и снова запустить `setup.cmd`. Скрипт увидит установленного агента, обновит
его и оставит ваш ключ, память и переписку. Прежний бандл можно не удалять — берётся
самый свежий по имени.

**Вручную**, если предпочитаете команды:

```powershell
cd $env:USERPROFILE\Downloads
git clone vasily-v1.0.2.bundle vasily-dist-new
Remove-Item -Recurse -Force .\vasily-dist-new\.git

hermes profile install .\vasily-dist-new --force --yes
```

Строка с удалением `.git` — не украшение: git помечает файлы внутри `.git/objects/pack`
атрибутом «только чтение», и установщик падает с `PermissionError: [WinError 5]`.
Если этой папки нет, строка ничего не делает.

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
| Установка не находит файл агента | файл не в текущем каталоге — проверить `cd $env:USERPROFILE\Downloads` и имя файла |
| `PermissionError: [WinError 5]` при обновлении | удалить папку `.git` в распакованном дистрибутиве перед установкой (шаг 7) |
| `WinError 32` — файл занят другим процессом | запущено приложение Hermes: значок в трее → Выход, затем запустить `setup.cmd` снова |
| Установка идёт слишком долго | первый запуск качает Python, Node и зависимости — это минуты, не ошибка |
| `vasily: команда не найдена` | `C:\Users\<вы>\.local\bin` не в PATH — использовать `hermes -p vasily chat` |
| Общий диагноз | `hermes -p vasily doctor` |
