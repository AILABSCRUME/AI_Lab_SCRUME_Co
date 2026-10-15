# AILab SCRUME Agent

Дистрибутив Hermes Agent: персона личного помощника, базовый конфиг, 58 скиллов.
Автор: AI laboratory SCRUM company.

**Получателю агента:** пошаговая инструкция — [`INSTALL.md`](INSTALL.md).
Короткий путь — распаковать архив и запустить `setup.cmd` двойным кликом: он ставит
Git, Hermes и агента, оставляет вписать только ключ. Доступ к репозиторию не нужен.

**Автору:** это исходник дистрибутива. Пакет для передачи собирается скриптом
`dist/vasily-setup/build-package.ps1` (имя папки историческое).

## Что внутри

| Путь | Что это |
|---|---|
| `distribution.yaml` | манифест: имя, версия, автор, требуемые переменные окружения |
| `SOUL.md` | персона агента: AILab SCRUME Agent, личный помощник |
| `config.yaml` | модель, провайдер (Polza.ai), инструменты, язык — **без ключей** |
| `skills/` | 58 штатных скиллов Hermes (документы, таблицы, PDF, поиск, почта, заметки, код) |
| `INSTALL.md` | пошаговая инструкция для получателя |
| `.env.template` | шаблон `.env`, устанавливается как `.env.EXAMPLE` |

Ключ API живёт только в `.env` получателя: в `config.yaml` стоит
`key_env: HERMES_CUSTOM_POLZA_AI_API_KEY` — имя переменной, а не значение.
В репозитории ключей нет.

## Куда ставится

Агент ставится в **корневой дом Hermes** (`%LOCALAPPDATA%\hermes`), а не в именованный
профиль. Так у получателя ровно один агент и нет меню профилей — это требование сборки.

`hermes profile install` здесь не используется: он умеет только именованные профили, а
запарковать корневой профиль ядро Hermes не даёт (намеренно игнорирует `gateway.parked`
для `default`). Поэтому `setup.ps1` копирует `SOUL.md`, `config.yaml` и `skills/` в корень
сам и ставит файл-маркер `.ailab-install.json`, по которому следующий запуск понимает,
что это обновление, а не чужая установка.

## Что не входит

- API-ключи, `auth.json`, пароли dashboard — только свои, локальные.
- MCP-серверы (Revit, AutoCAD и прочее) — не подключены, ставятся отдельно под свои задачи.
- SSH-бэкенд, cron-задачи, память и история автора.

## Передать получателю (файлом)

```bash
cd "$LOCALAPPDATA/hermes/dist/vasily-setup"
powershell -NoProfile -ExecutionPolicy Bypass -File build-package.ps1
```

Скрипт берёт версию из `distribution.yaml`, собирает бандл, копирует `setup.cmd`,
`setup.ps1`, `INSTALL.md`, `ПРОЧТИ-МЕНЯ.txt` и складывает всё в
`../ailab-setup-v<версия>.zip`.

Или вручную только бандл:

```bash
cd <этот каталог>
git bundle create ../ailab-v<версия>.bundle --all
git bundle verify ../ailab-v<версия>.bundle   # ожидается «is okay» + «complete history»
```

Получатель разворачивает по `INSTALL.md`.

## Обновить агента у получателя

Поднять `version` в `distribution.yaml`, закоммитить, поставить тег, пересобрать пакет
`build-package.ps1` и передать новый архив. Получателю достаточно положить новый
`ailab-<версия>.bundle` рядом со `setup.cmd` и запустить его снова: маркер в доме
подскажет, что это обновление, а `.env` с ключом, память и переписка не трогаются.

## Проверка перед передачей

Тест на подменённой машине — так собственный дом не участвует:

```powershell
# 1. "машина" получателя: рантайм без агента
$fake = 'C:\tmp\recv\AppData\Local'
New-Item -ItemType Directory "$fake\hermes" -Force
Copy-Item "$env:LOCALAPPDATA\hermes\tools" "$fake\hermes\tools" -Recurse
Copy-Item "$env:LOCALAPPDATA\hermes\bin"   "$fake\hermes\bin"   -Recurse

# 2. прогон установщика в ней
$env:LOCALAPPDATA = $fake
cd C:\tmp\recv\package          # распакованный ailab-setup-*.zip
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
```

Проверить после прогона: `%LOCALAPPDATA%\hermes\SOUL.md` (персона без имени автора),
58 скиллов, `.ailab-install.json` с версией, `.env` с ключом.

Публикация в git-репозиторий (вариант с обновлением одной командой):

```bash
git tag v<версия> && git push origin master --tags
```

## MCP (по желанию)

Добавляется уже в установленном агенте:

```bash
hermes mcp add <имя> --command <команда>
hermes mcp catalog          # посмотреть, что есть в каталоге
```
