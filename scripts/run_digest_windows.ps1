$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ProjectDir = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectDir

function Wait-BeforeExit {
    Write-Host ""
    Read-Host "Нажмите Enter, чтобы закрыть окно"
}

function Add-ToPathIfExists {
    param([string]$ExecutablePath)
    if ($ExecutablePath -and (Test-Path $ExecutablePath)) {
        $dir = Split-Path -Parent $ExecutablePath
        if ($env:PATH -notlike "*$dir*") {
            $env:PATH = "$dir;$env:PATH"
        }
        return $true
    }
    return $false
}

function Ensure-Codex {
    if (Get-Command codex -ErrorAction SilentlyContinue) {
        return
    }

    $candidates = @()
    if ($env:APPDATA) {
        $candidates += Join-Path $env:APPDATA "npm\codex.cmd"
        $candidates += Join-Path $env:APPDATA "npm\codex.exe"
    }
    if ($env:LOCALAPPDATA) {
        $candidates += Join-Path $env:LOCALAPPDATA "Programs\Codex\codex.exe"
        $candidates += Join-Path $env:LOCALAPPDATA "Codex\codex.exe"
    }
    if ($env:ProgramFiles) {
        $candidates += Join-Path $env:ProgramFiles "Codex\codex.exe"
    }
    $programFilesX86 = [Environment]::GetEnvironmentVariable("ProgramFiles(x86)")
    if ($programFilesX86) {
        $candidates += Join-Path $programFilesX86 "Codex\codex.exe"
    }

    foreach ($candidate in $candidates) {
        if (Add-ToPathIfExists $candidate) {
            return
        }
    }

    throw "Codex CLI не найден. Установите Codex CLI, войдите в аккаунт и проверьте, что команда codex доступна в PATH."
}

function New-Venv {
    $venvPython = Join-Path $ProjectDir ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        return $venvPython
    }

    Write-Host "Первый запуск: создаю локальное окружение Python..."

    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        & $pyLauncher.Source -3 -m venv .venv
    } else {
        $python = Get-Command python -ErrorAction SilentlyContinue
        if (-not $python) {
            throw "Python 3.10+ не найден. Установите Python с python.org и включите пункт Add python.exe to PATH."
        }
        & $python.Source -m venv .venv
    }

    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $venvPython)) {
        throw "Не удалось создать окружение Python."
    }
    return $venvPython
}

Write-Host "CHINT Russia: еженедельный дайджест"
Write-Host "===================================="

try {
    Ensure-Codex
    $python = New-Venv

    & $python -c "import digest, docx, googlenewsdecoder" *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Устанавливаю компоненты программы..."
        & $python -m pip install -e .
        if ($LASTEXITCODE -ne 0) {
            throw "Не удалось установить компоненты программы."
        }
    }

    Write-Host "Собираю выпуск. Это может занять несколько минут..."
    & $python -m digest.cli weekly
    if ($LASTEXITCODE -ne 0) {
        throw "Запуск завершился с ошибкой. Текст ошибки находится выше."
    }

    $latest = Get-ChildItem -Path (Join-Path $ProjectDir "outputs") -Filter "CHINT_digest_*.docx" |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1

    Write-Host ""
    if ($latest) {
        Write-Host "Готово: $($latest.FullName)"
        Start-Process -FilePath $latest.FullName
    } else {
        Write-Host "Готово, но Word-файл не найден в папке outputs."
    }
} catch {
    Write-Host ""
    Write-Host $_.Exception.Message
    exit 1
} finally {
    Wait-BeforeExit
}
