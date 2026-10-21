<#
    update-check.ps1 — ночная проверка обновлений дистрибутива AILab SCRUME Agent.

    Запускается задачей Планировщика 'AILabAgentUpdate' (создаётся установщиком).
    Порядок: узнать установленную версию → спросить у GitHub последний релиз →
    сравнить по ЧИСЛАМ → если новее, скачать, сверить и поставить.

    Ключевые решения (осознанные, не «по умолчанию»):

    * Обновление НЕ ставится, пока работает Hermes.exe: установщик подменяет
      файлы движка и окна, а занятые файлы он перезаписать не может. В этом
      случае пишем «отложено» и выходим — следующая ночь попробует снова.
      Насильно закрывать окно агента ночью скрипт не имеет права.
    * Установка идёт БЕЗ человека, поэтому запускается только если ключ уже
      вписан (.env на месте). Иначе это была бы первая установка, а её нельзя
      делать молча — там нужен Блокнот для ключа.
    * Скрипт зовёт setup.ps1 напрямую, а НЕ setup.cmd: у того в конце `pause`,
      и задача зависла бы навсегда, ожидая нажатия клавиши.

    Отключить: update-check.ps1 -Off   (снимает задачу Планировщика)
#>

[CmdletBinding()]
param(
    [switch]$Off,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

$HomeDir  = Join-Path $env:LOCALAPPDATA 'hermes'
$Marker   = Join-Path $HomeDir '.ailab-install.json'
$EnvFile  = Join-Path $HomeDir '.env'
$LogDir   = Join-Path $HomeDir 'logs'
$LogFile  = Join-Path $LogDir 'update-check.log'
$TaskName = 'AILabAgentUpdate'
$Repo     = 'AILABSCRUME/AI_Lab_SCRUME_Co'
$ApiUrl   = "https://api.github.com/repos/$Repo/releases/latest"
$ZipUrl   = "https://github.com/$Repo/releases/latest/download/agent-setup.zip"
$WorkDir  = Join-Path $env:LOCALAPPDATA 'ailab-setup'

function Write-Log {
    param([string]$Message)
    $stamp = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
    if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }
    Add-Content -Path $LogFile -Value "$stamp  $Message" -Encoding UTF8
}

# ---------- отключение ----------
if ($Off) {
    try {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop
        Write-Log 'задача снята (ключ -Off)'
        Write-Host 'Автообновление отключено.'
    } catch {
        Write-Log 'задача уже отсутствовала (ключ -Off)'
        Write-Host 'Автообновление и так выключено.'
    }
    exit 0
}

# ---------- только для уже установленного агента ----------
if (-not (Test-Path $Marker)) {
    Write-Log 'пропуск: след установки не найден (агент не установлен)'
    exit 0
}

if (-not (Test-Path $EnvFile)) {
    Write-Log 'пропуск: ключ ещё не вписан — молча ставить нельзя'
    exit 0
}

# ---------- версии ----------
function Get-NumericVersion {
    param([string]$Text)
    if ([string]::IsNullOrWhiteSpace($Text)) { return $null }
    $m = [regex]::Match($Text, '(\d+(?:\.\d+)*)')
    if (-not $m.Success) { return $null }
    $parts = @($m.Groups[1].Value.Split('.') | ForEach-Object { [int]$_ })
    while ($parts.Count -lt 4) { $parts += 0 }
    return $parts
}

function Compare-Version {
    param($A, $B)
    for ($i = 0; $i -lt 4; $i++) {
        if ($A[$i] -lt $B[$i]) { return -1 }
        if ($A[$i] -gt $B[$i]) { return 1 }
    }
    return 0
}

$installedRaw = $null
try {
    $installedRaw = (Get-Content -Path $Marker -Raw -Encoding UTF8 | ConvertFrom-Json).version
} catch {
    Write-Log "ошибка: не прочитал след установки — $($_.Exception.Message)"
    exit 1
}

$installed = Get-NumericVersion $installedRaw
if ($null -eq $installed) {
    Write-Log "ошибка: версия в следе не распознана ('$installedRaw')"
    exit 1
}

# ---------- спросить GitHub ----------
$latest = $null
try {
    $resp = Invoke-RestMethod -Uri $ApiUrl -Headers @{
        'User-Agent' = 'ailab-update-check'
        'Accept'     = 'application/vnd.github+json'
    } -TimeoutSec 45
    $latest = Get-NumericVersion $resp.tag_name
} catch {
    Write-Log "проверка не удалась (сеть/GitHub): $($_.Exception.Message)"
    exit 0
}

if ($null -eq $latest) {
    Write-Log "проверка не удалась: не разобрал тег релиза"
    exit 0
}

$cmp = Compare-Version $installed $latest

if ($cmp -ge 0) {
    Write-Log ("актуально: установлено {0}, на GitHub {1}" -f $installedRaw, $resp.tag_name)
    exit 0
}

# ---------- есть новее ----------
if (-not $Force) {
    $running = @(Get-Process -Name 'Hermes' -ErrorAction SilentlyContinue)
    if ($running.Count -gt 0) {
        Write-Log ("отложено: есть {0} — установка {1} поверх {2} невозможна при работающем окне" -f $resp.tag_name, $installedRaw, $resp.tag_name)
        exit 0
    }
}

Write-Log ("найдено обновление: {0} -> {1}, качаю" -f $installedRaw, $resp.tag_name)

# ---------- скачать и распаковать ----------
try {
    if (-not (Test-Path $WorkDir)) { New-Item -ItemType Directory -Path $WorkDir -Force | Out-Null }
    $zip = Join-Path $WorkDir 'agent-setup.zip'
    if (Test-Path $zip) { Remove-Item -Path $zip -Force }

    $ProgressPreference = 'SilentlyContinue'
    Invoke-WebRequest -Uri $ZipUrl -OutFile $zip -TimeoutSec 600

    $size = (Get-Item $zip).Length
    if ($size -lt 1MB) {
        Write-Log "обновление прервано: архив подозрительно мал ($size байт)"
        exit 1
    }

    $unpacked = Join-Path $WorkDir 'ailab'
    if (Test-Path $unpacked) { Remove-Item -Path $unpacked -Recurse -Force }
    Expand-Archive -Path $zip -DestinationPath $unpacked -Force
} catch {
    Write-Log "обновление прервано на загрузке: $($_.Exception.Message)"
    exit 1
}

$setup = Join-Path $unpacked 'setup.ps1'
if (-not (Test-Path $setup)) {
    Write-Log 'обновление прервано: в архиве нет setup.ps1'
    exit 1
}

# ---------- поставить (setup.ps1 напрямую: у setup.cmd в конце pause) ----------
try {
    $out = & powershell -NoProfile -ExecutionPolicy Bypass -File $setup 2>&1 | Out-String
    $code = $LASTEXITCODE
} catch {
    Write-Log "обновление упало: $($_.Exception.Message)"
    exit 1
}

if ($code -eq 0) {
    Write-Log ("обновление установлено: {0} -> {1}. Протокол: {2}" -f $installedRaw, $resp.tag_name, (Join-Path $unpacked 'setup-log.txt'))
} else {
    $tail = ($out -split "`n" | Select-Object -Last 3) -join ' | '
    Write-Log ("обновление упало (код $code): $tail")
}

exit $code
