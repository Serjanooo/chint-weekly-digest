#!/bin/zsh

set -u

PROJECT_DIR="${0:A:h}"
cd "$PROJECT_DIR" || exit 1
VENV_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/chint-weekly-digest/venv"
PYTHON_BIN="$VENV_DIR/bin/python"

echo "CHINT Russia: еженедельный дайджест"
echo "===================================="

if ! command -v codex >/dev/null 2>&1; then
  CODEX_APP_BIN="/Applications/Codex.app/Contents/Resources/codex"
  if [[ -x "$CODEX_APP_BIN" ]]; then
    export PATH="${CODEX_APP_BIN:h}:$PATH"
  else
    echo "Codex CLI не найден. Откройте приложение Codex и войдите в аккаунт."
    read "?Нажмите Enter, чтобы закрыть окно..."
    exit 1
  fi
fi

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Первый запуск: создаю локальное окружение Python..."
  mkdir -p "${VENV_DIR:h}" || {
    echo "Не удалось создать папку для окружения Python."
    read "?Нажмите Enter, чтобы закрыть окно..."
    exit 1
  }
  python3 -m venv "$VENV_DIR" || {
    echo "Не удалось создать окружение Python."
    read "?Нажмите Enter, чтобы закрыть окно..."
    exit 1
  }
fi

if ! "$PYTHON_BIN" -c "import digest, docx, googlenewsdecoder" >/dev/null 2>&1; then
  echo "Устанавливаю компоненты программы..."
  "$PYTHON_BIN" -m pip install -e "$PROJECT_DIR" || {
    echo "Не удалось установить компоненты программы."
    read "?Нажмите Enter, чтобы закрыть окно..."
    exit 1
  }
fi

echo "Собираю выпуск. Это может занять несколько минут..."
if "$PYTHON_BIN" -m digest.cli weekly; then
  latest_docx=$(ls -t outputs/CHINT_digest_*.docx 2>/dev/null | head -n 1)
  echo
  echo "Готово: $latest_docx"
  [[ -n "$latest_docx" ]] && open "$latest_docx"
else
  echo
  echo "Запуск завершился с ошибкой. Текст ошибки находится выше."
fi

echo
read "?Нажмите Enter, чтобы закрыть окно..."
