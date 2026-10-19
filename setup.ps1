# ============================================================
#  Установка агента AILab SCRUME Agent (Hermes Agent)
#  Обычно запускается двойным кликом по setup.cmd.
#  Вручную: powershell -NoProfile -ExecutionPolicy Bypass -File setup.ps1
#
#  Агент ставится в КОРНЕВОЙ профиль Hermes (~\hermes, он же "default"),
#  поэтому у получателя в системе ровно один агент и никаких
#  переключателей профилей. Парковка корневого профиля в Hermes не
#  работает (ядро её намеренно игнорирует), поэтому путь один — установка
#  в корень. Чужую существующую установку скрипт НЕ трогает: при первом
#  признаке чужого агента он останавливается.
#
#  Что делает скрипт (9 шагов):
#    1) находит дистрибутив рядом с собой
#    2) снимает метку "скачано из интернета"
#    3) проверяет, что дом свободен (чужой агент — стоп) — ДО любых записей
#    4) ставит Git и Hermes Agent, если их нет
#    5) копирует агента (при повторном запуске — обновляет)
#    6) открывает Блокнот для ключа
#    7) проверяет, что агент отвечает
#    8) прогревает окружение (pm repair): окно поднимает бэкенд и ждёт его
#       ответа 15 секунд, а на непрогретом доме зависимости ставятся минуты
#    8b) готовит движок ДЛЯ ОКНА: окно считает движок нерабочим, если
#       `hermes --version` не уложилась в 15 с (на холодном старте так и есть),
#       и тогда уходит в доустановку, где падает на первой же стадии. Здесь
#       даём окну запас по времени (HERMES_PROBE_TIMEOUT_MS) и указываем движок
#       явно (HERMES_DESKTOP_HERMES) — ничего не скачивая
#    9) скачивает и ставит ОКНО ПРИЛОЖЕНИЯ + ярлык на рабочем столе
#
#  Пользователю не нужно ничего, кроме ключа: ни второй команды, ни выбора
#  папки, ни отдельной загрузки приложения.
# ============================================================

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
$ProgressPreference = 'SilentlyContinue'

$Here    = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogFile = Join-Path $Here 'setup-log.txt'
$HomeDir = Join-Path $env:LOCALAPPDATA 'hermes'
$Marker  = Join-Path $HomeDir '.ailab-install.json'
$WorkDir = Join-Path $env:TEMP ('agent-setup-' + (Get-Random))

# Файлы, которые этот установщик кладёт в корневой профиль.
$OwnedFiles = @('SOUL.md', 'config.yaml')
$OwnedDirs  = @('skills')

# Куда ставится чип расхода Polza.ai (плагин + его скрипты):
#   * desktop-plugins\polza-limit\plugin.js   — один корень плагинов на всё приложение
#   * .polza-limits\*.py|*.cmd                — скрипты, которые плагин зовёт через shell.exec
# Отдельная папка (а не scripts профиля) — потому что корневой дом один.
$PluginDir   = Join-Path $HomeDir 'desktop-plugins\polza-limit'
$VersionDir  = Join-Path $HomeDir 'desktop-plugins\version-badge'
$HideMsgDir  = Join-Path $HomeDir 'desktop-plugins\hide-messaging'
$LimitsDir   = Join-Path $HomeDir '.polza-limits'

# Окно приложения (GUI). Это ОТДЕЛЬНЫЙ архив, он не входит в пакет агента, и
# получатель про него забывал: видел "ГОТОВО" и не понимал, где окно.
# Поэтому установщик сам скачивает, распаковывает и ставит ярлык — от
# пользователя не требуется ни второй команды, ни выбора папки.
# Ссылка без версии (releases/latest/download/...): не устареет при выпуске новой.
$AppUrl = 'https://github.com/AILABSCRUME/AI_Lab_SCRUME_Co/releases/latest/download/app-setup.zip'
# Та же сборка по неизменяемой ссылке с версией — на случай, если обновление
# релиза сломает latest ИЛИ админ отключил редирект. Пустая строка допустима.
# ВАЖНО: версия здесь должна существовать на GitHub. Стояла v1.3.6 — тот релиз
# удалили, ссылка стала 404, и сборщик пакета справедливо отказался собирать
# релиз с мёртвой ссылкой. Держим ссылку на ЖИВОЙ релиз и проверяем её
# сборщиком (build-package.ps1 проверяет все github-ссылки из setup.ps1).
$AppUrlFallback = 'https://github.com/AILABSCRUME/AI_Lab_SCRUME_Co/releases/download/v1.4.0/app-setup.zip'
$AppDir = Join-Path $env:LOCALAPPDATA 'AILabSCRUME\App'

function Line { param([string]$m = '') Write-Host $m }
function Step { param([string]$m) Line ''; Line ('=== ' + $m) }
function Ok   { param([string]$m) Write-Host ('  [ok] ' + $m) -ForegroundColor Green }
function Warn { param([string]$m) Write-Host ('  [!]  ' + $m) -ForegroundColor Yellow }
function Fail {
    param([string]$m)
    Line ''
    Write-Host ('[ОШИБКА] ' + $m) -ForegroundColor Red
    Line ''
    exit 1
}

# Признаки РАБОТАЮЩЕГО чужого агента. Наличие config.yaml, .env и skills/
# сюда НЕ входит: их создаёт сам официальный установщик Hermes, и на чистой
# машине они появляются сразу после установки — иначе установщик блокировал
# бы сам себя (проверено на живом прогоне 15.10.2026).
function Get-ForeignSigns {
    param([string]$Dir)
    $signs = @()
    if (-not (Test-Path $Dir)) { return $signs }

    # Персона: SOUL.md, поставленный Hermes, содержит стоковый текст.
    $soul = Join-Path $Dir 'SOUL.md'
    if (Test-Path $soul) {
        $t = Get-Content -Raw -Path $soul -ErrorAction SilentlyContinue
        if ($t -and ($t -notmatch 'You are Hermes Agent, built by Nous Research')) {
            $signs += 'SOUL.md — персона другого агента'
        }
    }

    # Память и переписка: реальные следы работы.
    foreach ($d in @('memories', 'sessions')) {
        $p = Join-Path $Dir $d
        if (Test-Path $p) {
            $n = @(Get-ChildItem -Path $p -File -ErrorAction SilentlyContinue).Count
            if ($n -gt 0) { $signs += ($d + ' — ' + $n + ' файлов') }
        }
    }

    if (Test-Path (Join-Path $Dir 'cron\jobs.json')) { $signs += 'cron — задачи по расписанию' }
    if (Test-Path (Join-Path $Dir 'auth.json'))     { $signs += 'auth.json — входы в сервисы' }

    # .env с вписанным ключом = агент настроен и работал.
    $envf = Join-Path $Dir '.env'
    if (Test-Path $envf) {
        if (Select-String -Path $envf -Pattern '^[A-Za-z_][A-Za-z0-9_]*_API_KEY=\S+' -Quiet -ErrorAction SilentlyContinue) {
            $signs += '.env — вписан API-ключ'
        }
    }

    # Именованные профили = кто-то уже настраивал Hermes под себя.
    $prof = Join-Path $Dir 'profiles'
    if (Test-Path $prof) {
        $named = @(Get-ChildItem -Path $prof -Directory -ErrorAction SilentlyContinue |
                   Where-Object { $_.Name -ne '.deleted' })
        if ($named.Count -gt 0) {
            $signs += ('профили: ' + (($named | ForEach-Object { $_.Name }) -join ', '))
        }
    }

    return $signs
}

try { Start-Transcript -Path $LogFile -Force | Out-Null } catch { Warn ('протокол в файл не пишется: ' + $LogFile) }

Line ''
Line '  УСТАНОВКА АГЕНТА AILAB SCRUME AGENT'
Line '  ---------------------------------------------'
Line ('  Папка: ' + $Here)

try {
    # ---------- 1. дистрибутив ----------
    Step '1/9  Ищу дистрибутив агента'
    # Версию сравниваем ЧИСЛАМИ, а не строками: при строковом сравнении
    # '1.3.8' больше '1.3.10' (символ '8' > '1'), и на десятом минорном
    # выпуске скрипт взял бы СТАРЫЙ бандл. Перебор явный: `Sort-Object`
    # со скриптблоком В ПЕРЕМЕННОЙ ранжирует неверно (проверено —
    # на наборе 1.3.2/1.3.8/1.3.9/1.3.10 выбрал 1.3.8).
    function Get-NewestBundle {
        param([string]$Dir, [string]$Pattern)
        $best = $null; $bestRank = -1
        foreach ($f in @(Get-ChildItem -Path $Dir -Filter $Pattern -File -ErrorAction SilentlyContinue)) {
            $m = [regex]::Match($f.Name, '(\d+)[._-](\d+)[._-](\d+)')
            $rank = if ($m.Success) {
                ([int]$m.Groups[1].Value) * 1000000 + ([int]$m.Groups[2].Value) * 1000 + [int]$m.Groups[3].Value
            } else { 0 }
            if ($rank -gt $bestRank) { $bestRank = $rank; $best = $f }
        }
        return $best
    }
    $Bundle = Get-NewestBundle $Here 'ailab-*.bundle'
    if (-not $Bundle) { $Bundle = Get-NewestBundle $Here '*.bundle' }
    if (-not $Bundle) {
        Fail 'Рядом со скриптом нет файла *.bundle. Положите setup.cmd и файл ailab-<версия>.bundle в одну папку.'
    }
    Ok ('найден: ' + $Bundle.Name + '  (' + [math]::Round($Bundle.Length / 1MB, 2) + ' МБ)')

    # ---------- 2. метка "скачано из интернета" ----------
    Step '2/9  Проверяю файлы'
    Get-ChildItem -Path $Here -Recurse -File -ErrorAction SilentlyContinue |
        ForEach-Object { try { Unblock-File -Path $_.FullName -ErrorAction Stop } catch {} }
    Ok 'метка "из интернета" снята (Windows может спросить подтверждение один раз)'

    # ---------- 3. снимок дома ДО любых записей ----------
    # Снимаем ПЕРВЫМ делом, до git и до движка: официальный установщик сам создаёт
    # config.yaml, .env и skills/ с 58 штатными скиллами, и после него
    # отличить свежую установку от работавшего агента уже нельзя.
    # Маркер нашего выпуска. Агент раньше назывался Dionis, поэтому старый файл
    # .dionis-install.json — тоже наш след: по нему установка понимает, что это
    # ОБНОВЛЕНИЕ, а не чужая машина.
    $markerData = $null
    foreach ($mk in @($Marker, (Join-Path $HomeDir '.dionis-install.json'))) {
        if ($markerData) { break }
        if (Test-Path $mk) {
            try { $markerData = Get-Content -Raw -Path $mk | ConvertFrom-Json } catch { $markerData = $null }
        }
    }
    $signsBefore  = @(Get-ForeignSigns $HomeDir)
    $hermesBefore = [bool](Get-Command hermes -ErrorAction SilentlyContinue) -or
                    (Test-Path (Join-Path $HomeDir 'bin\hermes.cmd'))

    # ---------- 6. защита чужих данных ----------
    Step '3/9  Проверяю, свободна ли установка'
    Line ('  корневой профиль: ' + $HomeDir)

    if ($markerData) {
        Ok ('здесь уже стоит AILab SCRUME Agent v' + $markerData.version + ' — обновляю его')
    } elseif ($signsBefore.Count -gt 0) {
        Line ''
        Write-Host '  На этой машине уже работал другой агент Hermes:' -ForegroundColor Yellow
        foreach ($f in $signsBefore) { Write-Host ('     - ' + $f) -ForegroundColor Yellow }
        Line ''
        Fail @'
Установка остановлена, чтобы НЕ ПОТЕРЯТЬ существующие данные.
Ничего не изменено и не установлено: проверка идёт до первой записи,
ваши настройки, ключи, память и переписка на месте.

Этот комплект ставит единственного агента AILab SCRUME Agent. Если на машине уже
работал другой агент, обратитесь к тому, кто передал вам архив:
нужна версия с отдельным профилем.
'@
    } elseif ($hermesBefore) {
        Ok 'Hermes стоял, но не настроен — ставлю поверх, ваших данных в нём нет'
    } else {
        Ok 'установка свободна — чужого агента не найдено'
    }


    # ---------- 3. git ----------
    # Git нужен и нам (распаковка дистрибутива), и официальному установщику
    # Hermes (он клонирует репозиторий). Ставим ЕГО ЖЕ артефактом и РОВНО в то
    # место, где официальный установщик его ищет:
    #     <дом>\tools\git-2.53.0+3-win32-x64\cmd\git.exe
    # Тогда его стадия prerequisites видит git и НИЧЕГО не качает.
    #
    # Почему не winget: он требует App Installer и ходит на cdn.winget.microsoft.com —
    # за корпоративным VPN этот путь отваливается молча, и установка умирала на Git.
    # Прямая ссылка GitHub проверена: 58 МБ, SHA совпадает, отдаёт 200.
    $GitPinVer  = '2.53.0+3'
    $GitPinSha  = 'b365da794b1d2225eb24d5f5e09ef7792cfd5fa26c3a3586210280c80dff3a2a'
    $GitPinUrl  = 'https://github.com/git-for-windows/git/releases/download/v2.53.0.windows.3/PortableGit-2.53.0.3-64-bit.7z.exe'
    $GitDir     = Join-Path $HomeDir ('tools\git-' + $GitPinVer + '-win32-x64')
    $GitExe     = Join-Path $GitDir 'cmd\git.exe'

    function Add-StagedGitToPath {
        if (Test-Path $GitExe) {
            $env:PATH = (Join-Path $GitDir 'cmd') + ';' + (Join-Path $GitDir 'usr\bin') + ';' + $env:PATH
            return $true
        }
        return $false
    }

    if (Get-Command git -ErrorAction SilentlyContinue) {
        Ok ('git: ' + (git --version))
    } elseif (Add-StagedGitToPath) {
        Ok ('git (переносимый, уже был): ' + (git --version))
    } else {
        Line '  git не найден — кладу переносимый (58 МБ, скачивается с GitHub)...'
        $gitOk = $false
        try {
            $tmpGit = Join-Path $env:TEMP ('ailab-git-' + (Get-Random))
            New-Item -ItemType Directory -Path $tmpGit -Force | Out-Null
            $sfx = Join-Path $tmpGit 'portable-git.7z.exe'
            Invoke-WebRequest -Uri $GitPinUrl -OutFile $sfx -UseBasicParsing -ErrorAction Stop
            $gotSha = (Get-FileHash -Path $sfx -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($gotSha -ne $GitPinSha) {
                Warn ('скачался не тот файл (SHA ' + $gotSha.Substring(0,12) + ') — пропускаю')
            } else {
                Ok ('скачано: ' + [math]::Round((Get-Item $sfx).Length / 1MB, 1) + ' МБ, SHA сошёлся')
                $unp = Join-Path $tmpGit 'unpacked'
                New-Item -ItemType Directory -Path $unp -Force | Out-Null
                Unblock-File -Path $sfx -ErrorAction SilentlyContinue
                # Self-extracting 7z: GUI-подсистема, поэтому через Process и с ожиданием.
                $proc = [System.Diagnostics.Process]::Start($sfx, ('-o"' + $unp + '" -y'))
                if (-not $proc.WaitForExit(600000)) {
                    try { $proc.Kill() } catch {}
                    Warn 'распаковка git не уложилась в 10 минут — пропускаю'
                } elseif (-not (Test-Path (Join-Path $unp 'cmd\git.exe'))) {
                    Warn 'в архиве git нет cmd\git.exe — пропускаю'
                } else {
                    if (Test-Path $GitDir) { Remove-Item -Recurse -Force $GitDir -ErrorAction SilentlyContinue }
                    New-Item -ItemType Directory -Path (Split-Path -Parent $GitDir) -Force | Out-Null
                    Move-Item $unp $GitDir
                    $gitOk = Add-StagedGitToPath
                }
            }
            Remove-Item $tmpGit -Recurse -Force -ErrorAction SilentlyContinue
        } catch {
            Warn ('переносимый git не поставился: ' + $_.Exception.Message)
        }
        if ($gitOk) { Ok ('git: ' + (git --version)) }
        else {
            Warn 'Git поставить не удалось. Установка продолжится: у официального'
            Line '  установщика Hermes есть свой запасной путь. Если он упадёт на стадии'
            Line '  prerequisites — установите Git for Windows: https://git-scm.com/download/win'
            Line '  и запустите setup.cmd снова.'
        }
    }

    # ---------- 5. Hermes Agent ----------
    Step '4/9  Проверяю Hermes Agent'

    function Resolve-Hermes {
        $c = Get-Command hermes -ErrorAction SilentlyContinue
        if ($c) { return $c.Source }
        $p = Join-Path $HomeDir 'bin\hermes.cmd'
        if (Test-Path $p) { return $p }
        return $null
    }

    # Запускается ли движок на самом деле. Пустой вывод = НЕ запускается:
    # лаунчер ссылается на питон абсолютным путём, и если пакет python не
    # доехал, падает мгновенно с 'Fatal error in launcher: Unable to create
    # process'. Такой движок не годен ни для окна, ни для `pm repair`.
    function Test-EngineRuns {
        param([string]$Path)
        if (-not $Path) { return '' }
        $v = ''
        try { $v = ((& $Path --version 2>&1) | Out-String).Trim() } catch { $v = '' }
        # Битый лаунчер печатает ТЕКСТ ОШИБКИ, а не пустоту:
        #   Fatal error in launcher: Unable to create process using
        #   '"<дом>\tools\python-...\python.exe" -I "..."'
        # Проверять только на пустоту мало — ошибка прошла бы как успех.
        if ($v -match '(?i)Fatal error in launcher|Unable to create process|не удается найти|cannot find the file') {
            return ''
        }
        # Отдаём только первую строку и только если она похожа на версию.
        $first = ($v -split "`r?`n" | Where-Object { $_.Trim() } | Select-Object -First 1)
        if (-not $first) { return '' }
        if ($first -match '(?i)Hermes Agent|v\d+\.\d+') { return $first.Trim() }
        return ''
    }

    # Пакеты в <дом>\tools не читаются пользователем. Признак: папка пакета
    # существует, но перечислить её содержимое нельзя — `Get-ChildItem` тихо
    # отдаёт 0 элементов. Так выглядит дом, где пакеты распакованы под ДРУГОЙ
    # учётной записью (обычно установку запускали «от имени администратора»):
    # `Test-Path` по самой папке даёт True, а файлов внутри не видно.
    # Внешне это ровно «движок не запускается»: лаунчер ссылается на
    # python.exe абсолютным путём и падает. Лечится не сетью, а правами.
    function Test-PackageAccess {
        param([string]$Root)
        if (-not $Root) { return '' }
        if (-not [IO.Directory]::Exists($Root)) { return '' }
        $dirs = @()
        try { $dirs = @(Get-ChildItem -LiteralPath $Root -Directory -Force -ErrorAction Stop) } catch { return '' }
        $denied = @()
        foreach ($d in $dirs) {
            # Точная проверка: НЕЧИТАЕМАЯ папка бросает UnauthorizedAccessException,
            # а просто ПУСТАЯ — нет. Разница важна: «пустой пакет» и «нет прав» —
            # разные причины и разные советы пользователю.
            try {
                $null = Get-ChildItem -LiteralPath $d.FullName -Force -ErrorAction Stop
            } catch [System.UnauthorizedAccessException] {
                $denied += $d.Name
            } catch { }
        }
        if ($denied.Count -eq 0) { return '' }
        return ($denied -join ', ')
    }

    # Повтор этапа, пока проверка не пройдёт. Нужен потому, что сеть у
    # получателя нестабильна: та же загрузка встаёт по таймауту, а со второго
    # раза проходит. Возвращает $true, если проверка прошла.
    function Invoke-WithRetry {
        param([string]$Title, [scriptblock]$Action, [scriptblock]$Check,
              [int]$Attempts = 3, [int]$PauseSec = 5)
        for ($i = 1; $i -le $Attempts; $i++) {
            try { if (& $Check) { return $true } } catch { }
            try { & $Action } catch { Warn ($Title + ': ' + $_.Exception.Message) }
            try { if (& $Check) { return $true } } catch { }
            if ($i -lt $Attempts) {
                Line ('  ' + $Title + ' — не прошло (попытка ' + $i + ' из ' + $Attempts + '), повторяю через ' + $PauseSec + ' с...')
                Start-Sleep -Seconds $PauseSec
            }
        }
        try { return (& $Check) } catch { return $false }
    }

    # Доустановка движка официальной лестницей. Она же добирает пакет python
    # и зависимости — ровно то, что осталось от оборванного запуска. Дом
    # задаём явно: иначе движок уедет туда, куда смотрит чужой HERMES_HOME.
    function Invoke-OfficialLadder {
        $prev = $env:HERMES_HOME
        $env:HERMES_HOME = $HomeDir
        try {
            $installer = [scriptblock]::Create((Invoke-RestMethod 'https://hermes-agent.nousresearch.com/install.ps1'))
            & $installer -NonInteractive
        } catch {
            Warn ('официальная доустановка не удалась: ' + $_.Exception.Message)
        } finally {
            if ($null -eq $prev) { Remove-Item Env:\HERMES_HOME -ErrorAction SilentlyContinue }
            else { $env:HERMES_HOME = $prev }
        }
        $env:PATH = [Environment]::GetEnvironmentVariable('PATH', 'User') + ';' +
                    [Environment]::GetEnvironmentVariable('PATH', 'Machine') + ';' + $env:PATH
        return (Resolve-Hermes)
    }

    $Hermes = Resolve-Hermes
    # Пустой вывод `--version` значит, что лаунчер НЕ запускается. Типичная
    # причина: не доехал пакет python, на который лаунчер ссылается
    # АБСОЛЮТНЫМ путём (<дом>\tools\python-<версия>-win32-x64\python.exe).
    # Тогда `hermes` падает мгновенно с 'Fatal error in launcher: Unable to
    # create process', и НИ `pm repair`, ни окно запуститься не могут.
    # Раньше это считалось «Hermes установлен» и установка врала про успех.
    $hermesVer = Test-EngineRuns $Hermes
    if (-not $hermesVer) {
        # Движка нет ИЛИ он есть, но не запускается. В обоих случаях лечится
        # официальной лестницей в тот же дом: она доставит и движок, и пакет
        # python, и зависимости. Повторяем — сеть у получателя рвётся по таймауту,
        # и со второй-третьей попытки та же загрузка обычно проходит.
        if ($Hermes) {
            Warn 'движок найден, но НЕ запускается (проба --version пуста)'
            Line '  Обычная причина — от прошлого запуска не доехал пакет python:'
            Line '  лаунчер ссылается на него и падает, унося с собой и `pm repair`.'
        } else {
            Warn 'Hermes Agent не установлен — ставлю. Это несколько минут, окно не закрывайте.'
        }
        Line '  Доставляю движок официальным установщиком в тот же дом...'

        $ok = Invoke-WithRetry 'Доустановка движка' {
            $script:Hermes = Invoke-OfficialLadder
        } {
            (Test-EngineRuns $script:Hermes) -ne ''
        } 3 10

        $Hermes = $script:Hermes
        $hermesVer = Test-EngineRuns $Hermes
        if (-not $ok -or -not $hermesVer) {
            $pyDir = Join-Path $HomeDir 'tools'
            Warn 'движок не запускается даже после повторов.'
            # Сначала исключаем права: этот случай лечится НЕ повтором установки,
            # и совет про VPN уводит в сторону. Признак — пакеты есть, но внутрь
            # не войти (см. Test-PackageAccess).
            $locked = Test-PackageAccess $pyDir
            if ($locked) {
                Line ''
                Line '  ПРИЧИНА: нет доступа к пакетам в папке:'
                Line ('     ' + $pyDir)
                Line ('  Не читаются: ' + $locked)
                Line ''
                Line '  Папки созданы под другой учётной записью — обычно установку'
                Line '  запускали «от имени администратора». Сеть тут ни при чём,'
                Line '  повторный запуск setup.cmd этого не исправит.'
                Line ''
                Line '  ЛЕЧЕНИЕ: рядом с setup.cmd лежит файл FIX.cmd. Нажмите на него'
                Line '  ПРАВОЙ кнопкой -> «Запуск от имени администратора», дождитесь'
                Line '  окончания, затем запустите setup.cmd ОБЫЧНЫМ пользователем.'
                Line '  (Ключ, память и переписка при починке не трогаются.)'
                Fail 'нет доступа к пакетам движка — установка остановлена.'
            }
            Line ('  Проверьте, что на месте пакет python в: ' + $pyDir)
            Line '  Чаще всего это сеть: VPN или прокси обрывают загрузки.'
            Line '  Выключите VPN и запустите setup.cmd снова — он продолжит'
            Line '  с места обрыва (загрузки возобновляемые, заново не качает).'
            Fail 'движок не запускается — установка остановлена, чтобы не выдать нерабочего агента.'
        }
        Ok 'движок готов'
    }
    Ok ('Hermes: ' + (($hermesVer -split "`n")[0]))

    # ---------- 6. распаковка и установка ----------
    Step '5/9  Устанавливаю агента'
    if (Test-Path $WorkDir) { Remove-Item -Recurse -Force $WorkDir -ErrorAction SilentlyContinue }
    New-Item -ItemType Directory -Path $WorkDir -Force | Out-Null
    $Dist = Join-Path $WorkDir 'dist'

    Line '  распаковываю дистрибутив...'
    $cloneOut = (& git clone --quiet $Bundle.FullName $Dist 2>&1 | Out-String)
    if (-not (Test-Path (Join-Path $Dist 'distribution.yaml'))) {
        Line $cloneOut
        Fail 'Не удалось распаковать дистрибутив (git clone).'
    }

    # .git убираем: на Windows он ставит файлам атрибут "только чтение"
    $dotGit = Join-Path $Dist '.git'
    if (Test-Path $dotGit) { Remove-Item -Recurse -Force $dotGit -ErrorAction SilentlyContinue }

    $ver = (Select-String -Path (Join-Path $Dist 'distribution.yaml') -Pattern '^version:\s*(.+)$').Matches[0].Groups[1].Value.Trim()

    # Копируем доставшийся агенту минимум в корневой профиль. Файлы пользователя
    # (.env, memories, sessions, cron, logs, auth.json) не трогаем никогда.
    if (-not (Test-Path $HomeDir)) { New-Item -ItemType Directory -Path $HomeDir -Force | Out-Null }

    $copied = @()
    foreach ($f in $OwnedFiles) {
        $src = Join-Path $Dist $f
        if (Test-Path $src) {
            Copy-Item $src (Join-Path $HomeDir $f) -Force
            $copied += $f
        }
    }
    foreach ($d in $OwnedDirs) {
        $src = Join-Path $Dist $d
        if (Test-Path $src) {
            $dst = Join-Path $HomeDir $d
            if (Test-Path $dst) { Remove-Item -Recurse -Force $dst -ErrorAction SilentlyContinue }
            Copy-Item $src $dst -Recurse -Force
            $copied += ($d + '\')
        }
    }
    # --- чип расхода Polza.ai: плагин + скрипты (необязательный компонент) ---
    $hasPlugin = Test-Path (Join-Path $Dist 'desktop-plugins\polza-limit\plugin.js')
    if ($hasPlugin) {
        New-Item -ItemType Directory -Path $PluginDir -Force | Out-Null
        Copy-Item (Join-Path $Dist 'desktop-plugins\polza-limit\plugin.js') $PluginDir -Force
        if (Test-Path (Join-Path $Dist 'scripts\polza-limits')) {
            New-Item -ItemType Directory -Path $LimitsDir -Force | Out-Null
            Copy-Item (Join-Path $Dist 'scripts\polza-limits\*') $LimitsDir -Recurse -Force
        }
        $copied += 'плагин чипа расхода'
    }
    # --- номер сборки в заголовке окна (необязательный компонент) ---
    # Строка состояния внизу скрыта в режиме Simple, а слоты заголовка
    # рендерятся всегда — поэтому версия показывается именно там.
    $hasBadge = Test-Path (Join-Path $Dist 'desktop-plugins\version-badge\plugin.js')
    if ($hasBadge) {
        New-Item -ItemType Directory -Path $VersionDir -Force | Out-Null
        Copy-Item (Join-Path $Dist 'desktop-plugins\version-badge\plugin.js') $VersionDir -Force
        $copied += 'плагин с номером сборки'
    }
    # --- «Сообщения» убраны из боковой навигации (необязательный компонент) ---
    # Мессенджеры у получателя не подключены, а вкладка ведёт в настройку
    # Telegram/Slack/Discord и шлюз сообщений. Скрывается только СТРОКА навигации —
    # возможность остаётся, клавиша и прямой адрес работают.
    $hasHide = Test-Path (Join-Path $Dist 'desktop-plugins\hide-messaging\plugin.js')
    if ($hasHide) {
        New-Item -ItemType Directory -Path $HideMsgDir -Force | Out-Null
        Copy-Item (Join-Path $Dist 'desktop-plugins\hide-messaging\plugin.js') $HideMsgDir -Force
        $copied += 'вкладка «Сообщения» скрыта'
    }

    Ok ('скопировано: ' + ($copied -join ', '))

    # Свой след: по нему следующая установка поймёт, что это ОБНОВЛЕНИЕ.
    $stamp = [ordered]@{
        agent      = 'ailab_scrume_agent'
        version    = $ver
        installed  = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ssK')
        source     = $Bundle.Name
    } | ConvertTo-Json
    [System.IO.File]::WriteAllText($Marker, $stamp, [System.Text.UTF8Encoding]::new($false))
    # Прежнее имя маркера чистим только при обновлении поверх Dionis
    $legacyMarker = Join-Path $HomeDir '.dionis-install.json'
    if ((Test-Path $legacyMarker) -and ($legacyMarker -ne $Marker)) { Remove-Item -Force $legacyMarker -ErrorAction SilentlyContinue }

    # ---------- 7. ключ ----------
    Step '6/9  Ключ API'
    $EnvFile    = Join-Path $HomeDir '.env'
    $EnvExample = Join-Path $HomeDir '.env.EXAMPLE'
    $KeyPattern = 'HERMES_CUSTOM_POLZA_AI_API_KEY=(\S+)'

    $haveKey = $false
    if (Test-Path $EnvFile) {
        if (Select-String -Path $EnvFile -Pattern $KeyPattern -Quiet -ErrorAction SilentlyContinue) { $haveKey = $true }
    }

    if ($haveKey) {
        Ok 'ключ уже вписан — шаг пропускаю'
    } else {
        if (Test-Path $EnvExample) { Copy-Item $EnvExample $EnvFile -Force }
        elseif (-not (Test-Path $EnvFile)) { New-Item -ItemType File -Path $EnvFile -Force | Out-Null }
        if (-not (Select-String -Path $EnvFile -Pattern 'HERMES_CUSTOM_POLZA_AI_API_KEY' -Quiet)) {
            Add-Content -Path $EnvFile -Value 'HERMES_CUSTOM_POLZA_AI_API_KEY='
        }

        Line ''
        Line '  Сейчас откроется Блокнот. Впишите полученный ключ после знака "="'
        Line '  без кавычек и пробелов, сохраните (Ctrl+S) и закройте Блокнот:'
        Line ''
        Line '        HERMES_CUSTOM_POLZA_AI_API_KEY=ваш_ключ'
        Line ''
        Read-Host '  Нажмите Enter, чтобы открыть Блокнот'
        try { Start-Process -FilePath notepad.exe -ArgumentList $EnvFile -Wait }
        catch { Warn ('Блокнот не открылся — впишите ключ вручную в файл: ' + $EnvFile) }

        if (Select-String -Path $EnvFile -Pattern $KeyPattern -Quiet -ErrorAction SilentlyContinue) { Ok 'ключ вписан' }
        else { Warn ('ключ пока пустой. Впишите его позже в файл: ' + $EnvFile) }
    }

    # ---------- 8. проверка ----------
    Step '7/9  Проверка'
    $keyOk = (Test-Path $EnvFile) -and (Select-String -Path $EnvFile -Pattern $KeyPattern -Quiet -ErrorAction SilentlyContinue)
    if ($keyOk) {
        # Проверяем ИМЕННО установленный агент: без явного HERMES_HOME команда
        # hermes из PATH может указывать на другую установку на этой машине.
        $prevHome = $env:HERMES_HOME
        $prevEap  = $ErrorActionPreference
        $env:HERMES_HOME = $HomeDir
        # Первый запуск в новом доме печатает в stderr подготовку зависимостей —
        # при ErrorActionPreference=Stop это выглядит как ошибка и рушит проверку.
        $ErrorActionPreference = 'Continue'

        # Берём ТОЛЬКО stdout. Если слить stderr (2>&1), в текст проверки попадает
        # служебный вывод, у которого в пути есть имя папки распаковки
        # распаковки), а -match в PowerShell регистронезависим — тогда ошибка
        # проходит как "ответ агента". Проверяли это на живом прогоне.
        # Строгий поиск имени: \b...\b обязателен, иначе 'AILab' находится ВНУТРИ
        # слова 'av|ailab|le' ('temporarily unavailable') — PowerShell -match
        # регистронезависим, и сообщение о сбое проходило как ответ агента.
        $NamePat = '\bAILab\b|\bSCRUME\b|помощник'
        Line '  спрашиваю агента, кто он...'

        # ЖЁСТКИЙ таймаут обязателен. При недоступном провайдере агент уходит в
        # лестницу авто-восстановления (agent.auto_recovery_cycles = 5, паузы
        # 15/30/60/60/60 с) и молчит минутами: обычный вызов (& hermes ...) висел
        # без конца и установка не заканчивалась. Start-Process + WaitForExit(ms)
        # возвращает управление всегда. Вывод пишем в файлы и читаем ПОСЛЕ
        # завершения процесса: при живом процессе редирект буферизует текст.
        $script:ProbeRaw = ''
        function Get-AgentAnswer {
            param([int]$TimeoutMs = 55000)
            $tmpBase = Join-Path ([System.IO.Path]::GetTempPath()) ('ailab-probe-' + [guid]::NewGuid().ToString('N'))
            $outF = $tmpBase + '.out'; $errF = $tmpBase + '.err'
            $raw = ''
            try {
                $p = Start-Process -FilePath $Hermes -NoNewWindow -PassThru -WorkingDirectory $HomeDir `
                     -ArgumentList 'chat -Q --oneshot -q "Как тебя зовут? Ответь одной строкой."' `
                     -RedirectStandardOutput $outF -RedirectStandardError $errF
                if (-not $p.WaitForExit($TimeoutMs)) { try { $p.Kill() } catch {}; Start-Sleep -Milliseconds 600 }
                foreach ($f in @($outF, $errF)) {
                    if (Test-Path $f) { $raw += ((Get-Content $f -Raw -ErrorAction SilentlyContinue) + "`n") }
                }
            } finally {
                Remove-Item $outF -Force -ErrorAction SilentlyContinue
                Remove-Item $errF -Force -ErrorAction SilentlyContinue
            }
            $script:ProbeRaw = $raw
            return ($raw -split "`r?`n" |
                    Where-Object { $_ -notmatch '\.ps1' -and $_ -notmatch 'знак\s*:' -and
                                   $_ -notmatch 'CategoryInfo|FullyQualifiedErrorId|Exception' })
        }

        try {
            $lines = Get-AgentAnswer
            $hit = ($lines | Where-Object { $_ -match $NamePat } | Select-Object -First 1)
            if (-not $hit) {
                # Свежий дом готовит зависимости при первом запуске — даём ему
                # закончить и пробуем ещё раз, прежде чем считать проверку неудачной.
                Line '  первый запуск: жду подготовки зависимостей и повторяю...'
                Start-Sleep -Seconds 20
                $lines = Get-AgentAnswer
                $hit = ($lines | Where-Object { $_ -match $NamePat } | Select-Object -First 1)
            }
        } finally {
            $ErrorActionPreference = $prevEap
            if ($null -eq $prevHome) { Remove-Item Env:\HERMES_HOME -ErrorAction SilentlyContinue }
            else { $env:HERMES_HOME = $prevHome }
        }

        if ($hit) {
            Ok ('агент отвечает: ' + $hit.Trim())
        } elseif ($script:ProbeRaw -match '401|403|Неверные учётные данные|rejected your API key|invalid[ _]api[ _]key') {
            # Ключ отклонён — ответ приходит быстро, это надёжный признак.
            Warn 'агент установлен, но провайдер отклонил API-ключ.'
            Line ('  Проверьте ключ в файле: ' + $EnvFile)
        } elseif ($script:ProbeRaw -match 'temporarily unavailable|retrying automatically|cycle \d+/|auto-recovery') {
            Warn 'агент установлен, но провайдер ответил "временно недоступен".'
            Line '  Ключ и установка в порядке — запустите приложение, всё готово.'
        } elseif ($script:ProbeRaw -match 'preparing dependencies|No module named|Installing Python') {
            Warn 'агент ещё готовит окружение (первый запуск).'
            Line '  Запустите setup.cmd ещё раз через минуту — установка не пострадала.'
        } elseif (-not $script:ProbeRaw.Trim()) {
            # Агент не ответил за отведённое время и ничего не напечатал: так ведёт
            # себя недоступный провайдер (агент молча ждёт восстановления).
            Warn 'агент не ответил за минуту — скорее всего провайдер недоступен.'
            Line '  Установка при этом в порядке: файлы и ключ на месте.'
            Line '  Запустите приложение; если не заработает — повторите setup.cmd позже.'
        } else {
            Warn 'агент не ответил про AILab SCRUME Agent — проверьте ключ и запустите setup.cmd снова.'
        }

    } else {
        Warn 'без ключа проверить агента нельзя — впишите ключ и запустите setup.cmd снова.'
    }

    # ---------- 8b. прогрев окружения ----------
    # Окно приложения поднимает `hermes serve` и ждёт его ВСЕГО 5 СЕКУНД
    # (DEFAULT_HEALTH_PROBE_TIMEOUT_MS). На непрогретом доме serve тратит
    # минуты на установку питоновских зависимостей — окно не дожидается и
    # висит в «waiting». Поэтому ставим окружение ЗАРАНЕЕ, до первого запуска.
    Step '8/9  Готовлю окружение'
    $origEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $prevHome2 = $env:HERMES_HOME
    $env:HERMES_HOME = $HomeDir
    try {
        # Готовность определяем по АРТЕФАКТУ, а не по `pm doctor`: на непрогретом
        # доме doctor печатает галочки по пакетам инструментов, хотя окружение
        # для serve ещё не собрано (проверено: ✓10 при 175 с до готовности).
        #
        # ВАЖНО: одной папки `venv` НЕДОСТАТОЧНО. Её создаёт стадия venv
        # ОФИЦИАЛЬНОЙ установки — то есть ДО того, как поедут зависимости, и
        # она остаётся от оборванного запуска. На живом случае это дало
        # '[ok] окружение уже готово' при МЁРТВОМ движке (не доехал пакет
        # python) — прогрев не запускался, и установка врала про успех.
        # Поэтому спрашиваем САМ движок: `--version` должен ответить.
        $envDir = Join-Path $HomeDir 'installs'
        $ready = $false
        if (Test-Path $envDir) {
            $ready = @(Get-ChildItem -Path $envDir -Recurse -Directory -Filter 'venv' -ErrorAction SilentlyContinue).Count -gt 0
        }
        if ($ready) {
            $probe = ''
            try { $probe = ((& $Hermes --version 2>&1) | Out-String).Trim() } catch { $probe = '' }
            if (-not $probe) {
                Warn 'окружение выглядит собранным, но движок не отвечает — прогоняю прогрев заново'
                $ready = $false
            }
        }

        if ($ready) {
            Ok 'окружение уже готово'
        } else {
            Line '  ставлю зависимости Python (~60 МБ). Это один раз и занимает'
            Line '  несколько минут на медленном интернете. Ниже идёт отчёт установки:'
            Line ''

            # Вывод идёт В ПОТОК, а не копится в переменную: молчащий шаг на
            # десять минут читается как зависание (первый получатель так и сказал).
            $logFile = Join-Path $Here 'pm.log'
            # Повтор: на нестабильном канале прогрев часто срывается по таймауту.
            # Критерий успеха — движок ОТВЕЧАЕТ, а не код возврата pm.
            $warmOk = $false
            foreach ($warmTry in 1..3) {
            if ($warmOk) { break }
            if ($warmTry -gt 1) {
                Line ('  прогрев не удался (попытка ' + ($warmTry-1) + ' из 3), повторяю через 15 с...')
                Start-Sleep -Seconds 15
            }
            $proc = Start-Process -FilePath $Hermes -NoNewWindow -PassThru `
                    -ArgumentList 'pm repair' -WorkingDirectory $HomeDir `
                    -RedirectStandardOutput $logFile -RedirectStandardError ($logFile + '.err')
            # Потолок 10 минут: дальше продолжаем без прогрева. Агент работает и
            # без него — просто окно при первом запуске откроется не сразу.
            $deadline = (Get-Date).AddMinutes(10)
            while (-not $proc.HasExited -and (Get-Date) -lt $deadline) {
                Start-Sleep -Seconds 5
                if (Test-Path $logFile) {
                    $tail = Get-Content $logFile -Tail 1 -ErrorAction SilentlyContinue
                    if ($tail) { Line ('    ' + ($tail -join ' ').Trim()) }
                }
            }
            $timedOut = -not $proc.HasExited
            if ($timedOut) { try { $proc.Kill() } catch {} }

            $out = ''
            foreach ($f in @($logFile, ($logFile + '.err'))) {
                if (Test-Path $f) { $out += ((Get-Content $f -Raw -ErrorAction SilentlyContinue) + "`n") }
            }
            Remove-Item $logFile -Force -ErrorAction SilentlyContinue
            Remove-Item ($logFile + '.err') -Force -ErrorAction SilentlyContinue

            if ($timedOut) {
                Warn 'прогрев не уложился в 10 минут — продолжаю установку.'
                Line '  Агент работает и так; окно при первом запуске откроется не сразу.'
                Line '  Позже можно повторить:  hermes pm repair'
            } elseif ($out -match '(?i)\bfailed\b|\berror\b') {
                Warn 'прогрев завершился с замечаниями — это не мешает работе агента.'
                Line '  Позже можно повторить:  hermes pm repair'
            } else {
                Ok 'окружение готово'
            }
            if (Test-EngineRuns $Hermes) {
                $warmOk = $true
            } else {
                Warn 'после прогрева движок всё ещё не отвечает'
            }
            }   # конец цикла прогрева

            # Пакеты для скиллов документов: Excel, Word, PDF, PowerPoint.
            # Без них агент УМЕЕТ только ЧИТАТЬ готовые файлы (read_file разбирает
            # .xlsx/.docx/.pptx сам), а создать или изменить НЕ может: скрипты
            # скиллов делают `import openpyxl` / `docx` / `pptx` / `pypdf`, и на
            # чистом доме это ModuleNotFoundError. Проверено на живом доме:
            # xlsx, docx, pptx и pdf создаются и читаются обратно.
            #
            # Ставим в venv ДВИЖКА, а не в набортный `tools\python-*`: агент в
            # терминале видит именно venv (в нём свой PATH), у набортного питона
            # свои пакеты и он не в PATH. Через `uv pip`, потому что в venv движка
            # НЕТ pip (`No module named pip`), а uv лежит в tools после прогрева.
            # Венв может быть не один — ставим во ВСЕ найденные: на живом доме их
            # два, и `python` в PATH указывал НЕ на тот, куда поставили пакеты.
            #
            # Не критично для установки: не получилось — скажем и продолжим.
            if ($warmOk) {
                # edge-tts обновляем ОТДЕЛЬНО и принудительно: в 7.2.7 синтез речи
                # отвечает 403 (проверено на живой машине — Microsoft сменил
                # требование к токену), а в 7.3.1 работает. Без обновления голос
                # молчит, хотя библиотека установлена.
                $docPkgs = @('openpyxl', 'python-docx', 'python-pptx', 'pypdf', 'reportlab', 'pdfplumber', 'pypdfium2', 'edge-tts')
                Line ('  ставлю пакеты документов и голоса (' + ($docPkgs -join ', ') + ')...')
                try {
                    $uvExe = $null
                    $uvDir = Get-ChildItem -Path (Join-Path $HomeDir 'tools') -Directory -Filter 'uv-*' -ErrorAction SilentlyContinue |
                             Select-Object -First 1
                    if ($uvDir) {
                        $cand = Join-Path $uvDir.FullName 'uv.exe'
                        if (Test-Path $cand) { $uvExe = $cand }
                    }
                    $pyList = @()
                    foreach ($envDir in @(Get-ChildItem -Path (Join-Path $HomeDir 'installs') -Recurse -Directory -Filter 'venv' -ErrorAction SilentlyContinue)) {
                        $cand = Join-Path $envDir.FullName 'Scripts\python.exe'
                        if (Test-Path $cand) { $pyList += $cand }
                    }
                    if (-not $uvExe) {
                        Warn 'не нашёл uv — пакеты документов пропущены'
                    } elseif ($pyList.Count -eq 0) {
                        Warn 'не нашёл python движка — пакеты документов пропущены'
                    } else {
                        $allOk = $true
                        foreach ($pyForAgent in $pyList) {
                            $null = (& $uvExe pip install --python $pyForAgent @docPkgs 2>&1 | Out-String)
                            # Голос: edge-tts обязан быть >= 7.3 — на 7.2.7 синтез даёт 403.
                            $null = (& $uvExe pip install --python $pyForAgent -U edge-tts 2>&1 | Out-String)
                            # Проверяем не код возврата uv, а РЕАЛЬНЫЙ импорт в этом питоне.
                            $probePkg = (& $pyForAgent -c "import openpyxl, docx, pptx, pypdf; print('ok')" 2>&1 | Out-String).Trim()
                            if ($probePkg -ne 'ok') { $allOk = $false }
                        }
                        if ($allOk) {
                            Ok ('пакеты документов на месте (движков: ' + $pyList.Count + ')')
                        } else {
                            Warn 'часть пакетов документов не встала — скиллы Excel/Word/PDF/PowerPoint не смогут создавать файлы'
                            Line '  Позже можно повторить:  uv pip install --python <venv\Scripts\python.exe> openpyxl python-docx python-pptx pypdf reportlab pdfplumber'
                        }
                    }
                } catch {
                    Warn ('пакеты документов: ' + $_.Exception.Message)
                }
            }
            if (-not $warmOk) {
                $locked2 = Test-PackageAccess (Join-Path $HomeDir 'tools')
                if ($locked2) {
                    Warn 'прогрев не удался: нет доступа к пакетам.'
                    Line ('  Не читаются: ' + $locked2)
                    Line '  Папки созданы под другой учётной записью (установка «от администратора»).'
                    Line '  Лечение: от администратора — takeown и icacls на дом, затем setup.ps1'
                    Line '  ОБЫЧНЫМ пользователем. Подробности печатает шаг 4/9.'
                    Fail 'нет доступа к пакетам — установка не завершена.'
                }
                Warn 'прогрев не удался за три попытки.'
                Line '  Чаще всего это сеть: выключите VPN и запустите setup.cmd снова —'
                Line '  загрузки возобновляемые, заново качать не будет.'
                Fail 'окружение не готово — установка не завершена.'
            }
        }
    } catch {
        Warn ('прогрев не выполнился: ' + $_.Exception.Message)
        Line '  Агент работает и без него — просто окно откроется не сразу.'
    } finally {
        $ErrorActionPreference = $origEap
        if ($null -eq $prevHome2) { Remove-Item Env:\HERMES_HOME -ErrorAction SilentlyContinue }
        else { $env:HERMES_HOME = $prevHome2 }
    }

    # ---------- 8b. движок для окна ----------
    # Окно поднимает движок только если его проба укладывается в 15 секунд
    # (backend-probes.ts: DEFAULT_PROBE_TIMEOUT_MS). На холодном старте Windows
    # `hermes --version` идёт 13 с и больше (замерено: 13.45 с против 3.37 с на
    # тёплом) — в лимит не укладывается. Тогда окно считает движок нерабочим,
    # уходит в доустановку, качает официальный install.ps1 и падает на первой же
    # стадии, «System prerequisites» (переносимый Git), с ошибкой «Отказано в
    # доступе». Для получателя это выглядит как «Ошибка установки».
    # Лечим ПРИЧИНУ, а не следствие: даём окну запас по времени пробы и
    # указываем движок явно. Тогда доустановка не запускается вовсе.
    #
    # Git сюда НЕ скачиваем: это 55 МБ и лишняя точка отказа ради стадии,
    # которой при работающем движке не бывает. Официальный установщик поставит
    # свой Git сам, если он когда-нибудь всё же понадобится (например, при
    # штатном обновлении движка через `hermes update`).
    Step '8b/9  Готовлю движок для окна'
    try {
        # Лаунчер движка. Порядок: сначала тот, что публикует сам движок,
        # затем исторический пользовательский bin.
        $launcher = $null
        foreach ($cand in @((Join-Path $HomeDir 'hermes-agent\.hermes\bin\hermes.exe'),
                            (Join-Path $HomeDir 'hermes-agent\.hermes\bin\hermes.cmd'),
                            (Join-Path $HomeDir 'bin\hermes.exe'),
                            (Join-Path $HomeDir 'bin\hermes.cmd'))) {
            if (Test-Path $cand) { $launcher = $cand; break }
        }

        if ($launcher) {
            # Прогреваем ровно ту пробу, которую делает окно (`--version`), и меряем.
            $t0 = Get-Date
            $vOut = (& $launcher --version 2>&1 | Out-String)
            $probeSec = [int](((Get-Date) - $t0).TotalSeconds)
            Line ('  проба движка: ' + $probeSec + ' с (' + (($vOut.Trim() -split "`n")[0]) + ')')
            if ($probeSec -ge 12) {
                Warn 'проба идёт долго (холодный старт) — именно из-за этого окно уходило в доустановку'
            }

            # Движок не отвечает: ставить метку «установка завершена» НЕЛЬЗЯ.
            # Метка — это обещание окну, что движок рабочий; с мёртвым движком
            # окно просто получит нерабочий бэкенд, а получатель — «работает»,
            # которого нет. Раньше проба '0 с ()' считалась нормой.
            $engineOk = Test-EngineRuns $launcher
            if (-not $engineOk) {
                Warn 'движок не отвечает — метку завершения НЕ ставлю'
                Line '  Окно всё равно останется при своём движке (переменные ниже',
                Line '  выставлены), но установка не считается завершённой.'
                Line '  Запустите setup.cmd снова: он доставит недостающее и повторит.'
                throw 'движок не отвечает на пробу — пропускаю шаг 8b'
            }

            # (1) Запас окну: дефолтные 15 с малы для холодного старта Windows.
            # Замеры: 13.45 с на холодном движке против 3.37 с на тёплом.
            [Environment]::SetEnvironmentVariable('HERMES_PROBE_TIMEOUT_MS', '120000', 'User')
            $env:HERMES_PROBE_TIMEOUT_MS = '120000'
            # (2) Явный движок: с ним окно не делает пробу вообще — доверяет
            # значению (штатный приём для сборок-раскладок).
            [Environment]::SetEnvironmentVariable('HERMES_DESKTOP_HERMES', $launcher, 'User')
            $env:HERMES_DESKTOP_HERMES = $launcher

            # Говорим системе об изменении окружения: иначе Проводник отдаст
            # ярлыку старые переменные до следующего входа в систему.
            try {
                Add-Type -Namespace AILab -Name Env -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("user32.dll", SetLastError=true, CharSet=System.Runtime.InteropServices.CharSet.Auto)]
public static extern System.IntPtr SendMessageTimeout(System.IntPtr hWnd, uint Msg, System.UIntPtr wParam, string lParam, uint fuFlags, uint uTimeout, out System.UIntPtr lpdwResult);
'@ -ErrorAction Stop
                $res = [UIntPtr]::Zero
                [void][AILab.Env]::SendMessageTimeout([IntPtr]0xffff, 0x1a, [UIntPtr]::Zero, 'Environment', 0x2, 5000, [ref]$res)
            } catch { }


            # (3) ГЛАВНОЕ. Приложение собрано как «bootstrap»: движка внутри него
            # нет, и при первом запуске окно ОБЯЗАНО занять дом — оно идёт в
            # официальный install.ps1 (ставит движок с GitHub, без AILab-брендинга
            # и без следов работы; у нас падало на самой первой стадии,
            # «Отказано в доступе»). Метка .hermes-bootstrap-complete говорит окну,
            # что установка уже завершена, и доустановка не запускается вообще.
            #
            # ВАЖНО: приложение признаёт метку только если в ней есть поле
            # pinnedCommit — строка из 7..40 шестнадцатеричных знаков, и НЕ из
            # одних нулей (`hasValidBootstrapMarker`). Любое другое значение
            # (например 'ailab-123') метку обесценивает: окно прочитает её и
            # всё равно уйдёт в доустановку. Поэтому берём коммит ровно так же,
            # как это делает само приложение: HEAD дерева движка; если .git нет —
            # коммит из штампа установленного приложения.
            $markerFile = Join-Path $HomeDir 'hermes-agent\.hermes-bootstrap-complete'
            $engineRoot = Join-Path $HomeDir 'hermes-agent'
            if (Test-Path $engineRoot) {
                $pinCommit = $null
                $pinBranch = 'main'
                try {
                    $head  = (& git -C $engineRoot rev-parse HEAD 2>$null | Select-Object -First 1)
                    $head  = if ($head) { $head.Trim() } else { '' }
                    if ($head -match '^[0-9a-fA-F]{7,40}$' -and $head -notmatch '^0+$') {
                        $pinCommit = $head.ToLowerInvariant()
                        $br = (& git -C $engineRoot rev-parse --abbrev-ref HEAD 2>$null | Select-Object -First 1)
                        if ($br -and $br.Trim() -and $br.Trim() -ne 'HEAD') { $pinBranch = $br.Trim() }
                    }
                } catch { }

                # Дерева .git нет — берем коммит из штампа приложения: он и так
                # описывает, из чего собран движок, и приложение само сверяется с ним.
                if (-not $pinCommit) {
                    foreach ($stampPath in @(
                        (Join-Path $AppDir 'resources\install-stamp.json'),
                        (Join-Path $AppDir 'install-stamp.json'))) {
                        if ($pinCommit) { break }
                        if (Test-Path $stampPath) {
                            try {
                                $st = Get-Content -Raw -Path $stampPath | ConvertFrom-Json
                                if ($st.commit -match '^[0-9a-fA-F]{7,40}$' -and $st.commit -notmatch '^0+$') {
                                    $pinCommit = $st.commit.ToLowerInvariant()
                                    if ($st.branch) { $pinBranch = $st.branch }
                                }
                            } catch { }
                        }
                    }
                }

                if ($pinCommit) {
                    $stampData = [ordered]@{
                        schemaVersion = 1
                        pinnedCommit  = $pinCommit
                        pinnedBranch  = $pinBranch
                        completedAt   = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss.fffZ')
                        desktopVersion = $ver
                        source        = 'ailab-setup'
                        agent         = 'ailab_scrume_agent'
                        launcher      = $launcher
                    } | ConvertTo-Json -Depth 4
                    [System.IO.File]::WriteAllText($markerFile, $stampData, [System.Text.UTF8Encoding]::new($false))
                    Ok ('окну сказано: установка завершена (метка, коммит ' + $pinCommit.Substring(0,7) + ')')
                } else {
                    Warn 'не удалось определить коммит движка — метку завершения не поставил'
                    Line '  Окно может попробовать доустановку. Запустите setup.cmd снова.'
                }
            } else {
                Warn 'дерева hermes-agent нет — метку завершения поставить некуда'
            }

            Ok 'окну указан движок и дан запас по времени пробы'
        } else {
            Warn 'лаунчер движка не найден — окно будет искать его само'
        }
    } catch {
        # Установку не рушим: агент работает и без этого шага. Но говорим прямо.
        Warn ('подготовка движка для окна не удалась: ' + $_.Exception.Message)
        Line '  Агент при этом работает. Если окно покажет ошибку установки —'
        Line '  запустите setup.cmd ещё раз и напишите автору агента.'
    }

    # ---------- 9. окно приложения ----------
    # ОДНОЙ кнопки достаточно: агент + приложение + ярлык. Пользователь ничего
    # не выбирает и никуда не ходит. Если приложение уже стоит — только ярлык.
    Step '9/9  Ставлю окно приложения'
    $appExe = Join-Path $AppDir 'Hermes.exe'
    $appOk  = $false

    if (Test-Path $appExe) {
        Ok ('приложение уже стоит: ' + $AppDir)
        $appOk = $true
    } else {
        $zip = Join-Path $env:TEMP 'ailab-app.zip'
        Line '  скачиваю приложение (~158 МБ, это несколько минут)...'
        # Повторяем и в пределах одной попытки (две ссылки), и между попытками:
        # на нестабильном канале 158 МБ редко проходят с первого раза.
        $downloaded = $false
        foreach ($attempt in 1..3) {
            if ($downloaded) { break }
            foreach ($u in @($AppUrl, $AppUrlFallback)) {
                if ($downloaded) { break }
                if (-not $u) { continue }
                try {
                    # BITS быстрее и умеет продолжать, но на части машин недоступен —
                    # тогда обычный запрос. $ProgressPreference уже SilentlyContinue:
                    # иначе Invoke-WebRequest рисует полосу и тормозит в разы.
                    if (Test-Path $zip) { Remove-Item $zip -Force -ErrorAction SilentlyContinue }
                    Invoke-WebRequest -Uri $u -OutFile $zip -UseBasicParsing -ErrorAction Stop
                    if ((Get-Item $zip).Length -gt 20MB) { $downloaded = $true }
                } catch {
                    Warn ('не скачалось: ' + $_.Exception.Message)
                }
            }
            if (-not $downloaded -and $attempt -lt 3) {
                Line ('  приложение не скачалось (попытка ' + $attempt + ' из 3), повторяю через 10 с...')
                Start-Sleep -Seconds 10
            }
        }
        if (-not $downloaded) {
            Warn 'НЕ удалось скачать приложение после трёх попыток.'
            Line '  Агент при этом поставлен и работает.'
            Line '  Чаще всего это сеть: выключите VPN и запустите setup.cmd снова —'
            Line '  он докачает только приложение, агента ставить не будет.'
            Fail 'окно приложения не поставлено — установка не завершена.'
        } else {
            Ok ('скачано: ' + [math]::Round((Get-Item $zip).Length / 1MB, 1) + ' МБ')
            Line '  распаковываю...'
            try {
                if (Test-Path $AppDir) { Remove-Item -Recurse -Force $AppDir -ErrorAction SilentlyContinue }
                New-Item -ItemType Directory -Path $AppDir -Force | Out-Null
                Expand-Archive -Path $zip -DestinationPath $AppDir -Force -ErrorAction Stop
                if (Test-Path $appExe) { $appOk = $true; Ok ('распаковано в ' + $AppDir) }
                else { Warn 'распаковалось, но Hermes.exe не найден — архив повреждён?' }
            } catch {
                Warn ('не удалось распаковать: ' + $_.Exception.Message)
            }
        }
        Remove-Item $zip -Force -ErrorAction SilentlyContinue
    }

    # Ярлык на рабочий стол. Ставим и когда приложение уже было — ярлыка могло не быть.
    if ($appOk) {
        $mk = Join-Path $AppDir 'make-shortcut.ps1'
        if (Test-Path $mk) {
            # Через Start-Process: скрипт сам печатает итог, ошибки не должны
            # рушить установку (разрешения на .lnk, политика выполнения).
            $mkOut = (& powershell -NoProfile -ExecutionPolicy Bypass -File $mk 2>&1 | Out-String)
            $lnk = Join-Path ([Environment]::GetFolderPath('Desktop')) 'AILab SCRUME Agent.lnk'
            if (Test-Path $lnk) { Ok 'ярлык «AILab SCRUME Agent» на рабочем столе' }
            else {
                Warn 'ярлык не создался. Создайте его сами — двойной клик по:'
                Line ('    ' + (Join-Path $AppDir 'make-shortcut.cmd'))
                Line $mkOut.Trim()
            }
        } else {
            # Старые сборки приложения шли без скрипта ярлыка: делаем сами.
            try {
                $lnk = Join-Path ([Environment]::GetFolderPath('Desktop')) 'AILab SCRUME Agent.lnk'
                $ic  = Join-Path $AppDir 'resources\icon.ico'
                $sh  = New-Object -ComObject WScript.Shell
                $sc  = $sh.CreateShortcut($lnk)
                $sc.TargetPath = $appExe
                $sc.WorkingDirectory = $AppDir
                if (Test-Path $ic) { $sc.IconLocation = $ic }
                $sc.Save()
                if (Test-Path $lnk) { Ok 'ярлык «AILab SCRUME Agent» на рабочем столе' }
            } catch { Warn ('ярлык не создался: ' + $_.Exception.Message) }
        }
    }

    # Последняя проверка перед «ГОТОВО»: движок должен реально отвечать.
    # Без неё установка рапортовала об успехе при мёртвом движке (не доехал
    # пакет python), и получатель узнавал правду только при запуске окна.
    $finalVer = ''
    try { $finalVer = Test-EngineRuns $Hermes } catch { $finalVer = '' }
    if (-not $finalVer) {
        $Hermes2 = Invoke-OfficialLadder
        $finalVer = Test-EngineRuns $Hermes2
    }

    Line ''
    Line '  ---------------------------------------------'
    if ($finalVer) {
        Line '  ГОТОВО.'
    } else {
        Line '  УСТАНОВКА НЕ ЗАВЕРШЕНА.'
        Line ''
        Line '  Движок Hermes не запускается, поэтому агент работать не будет.'
        # Права проверяем ПЕРВЫМИ: это состояние повторный запуск не лечит,
        # и совет «попробуйте ещё раз»/«это сеть» уводит в сторону.
        $locked3 = Test-PackageAccess (Join-Path $HomeDir 'tools')
        if ($locked3) {
            Line ''
            Line '  ПРИЧИНА: нет доступа к пакетам движка. Не читаются:'
            Line ('     ' + $locked3)
            Line ''
            Line '  Папки созданы под другой учётной записью — установку запускали'
            Line '  «от имени администратора». Сеть тут ни при чём.'
            Line ''
            Line '  ЛЕЧЕНИЕ: запустите от администратора файл FIX.cmd из папки, куда'
            Line '  распакован архив (двойной клик по нему — нет, правой кнопкой:'
            Line '  «Запуск от имени администратора»). Дождитесь окончания, затем'
            Line '  запустите setup.cmd ОБЫЧНЫМ пользователем.'
        } else {
            Line '  Скорее всего от прошлого запуска не доехали зависимости — это сеть.'
            Line '  Запустите setup.cmd ещё раз: он продолжит с места обрыва.'
        }
        Line ''
        Line '  Если повторится — пришлите автору файл протокола:'
        Line ('     ' + $LogFile)
        exit 1
    }
    Line ''
    if ($appOk) {
        Line '  Запуск: ярлык «AILab SCRUME Agent» на рабочем столе'
        Line ('  или файл: ' + $appExe)
    } else {
        Warn 'окно приложения ещё не поставлено — см. сообщение выше.'
        Line '  Агент работает: в чате через командную строку он отвечает.'
    }
    Line ''
    Line '  Персона, имя владельца, тон — файл:'
    Line ('     ' + (Join-Path $HomeDir 'SOUL.md'))
    Line ''
    Line ('  Ключ: ' + $EnvFile)
    Line ('  Протокол установки: ' + $LogFile)
    Line ''

    exit 0
}
finally {
    try { Stop-Transcript | Out-Null } catch {}
    if (Test-Path $WorkDir) { Remove-Item -Recurse -Force $WorkDir -ErrorAction SilentlyContinue }
}
