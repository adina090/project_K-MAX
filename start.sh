#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_RUNNER="$PROJECT_DIR/.venv/bin/uvicorn"
FRONTEND_DIR="$PROJECT_DIR/frontend"
VITE_RUNNER="$FRONTEND_DIR/node_modules/.bin/vite"

if [[ -f "$PROJECT_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$PROJECT_DIR/.env"
  set +a
fi

if [[ -f "$PROJECT_DIR/.env.local" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$PROJECT_DIR/.env.local"
  set +a
fi

DEVICE_NAME="$(hostname -s)"
APP_DOMAIN="${APP_DOMAIN:-${DEVICE_NAME}.local}"

if [[ ! "$APP_DOMAIN" =~ ^[A-Za-z0-9.-]+$ ]]; then
  echo "APP_DOMAIN에는 프로토콜이나 경로 없이 도메인 이름만 입력해 주세요."
  echo "예: APP_DOMAIN=health-companion.local"
  exit 1
fi

export APP_DOMAIN

if [[ ! -x "$BACKEND_RUNNER" ]]; then
  echo "FastAPI 실행 환경이 없습니다. 다음 명령을 먼저 실행해 주세요:"
  echo "  python3 -m venv .venv"
  echo "  .venv/bin/python -m pip install -r backend/requirements.txt"
  exit 1
fi

if [[ ! -x "$VITE_RUNNER" ]]; then
  echo "프론트엔드 패키지가 설치되지 않았습니다. 다음 명령을 먼저 실행해 주세요:"
  echo "  cd frontend && npm install"
  exit 1
fi

port_in_use() {
  lsof -nP -iTCP:"$1" -sTCP:LISTEN -t >/dev/null 2>&1
}

if port_in_use 8000 || port_in_use 5173; then
  echo "서버를 시작하지 못했습니다. 이미 사용 중인 포트가 있습니다."
  if port_in_use 8000; then
    echo "  - 8000번 포트: FastAPI가 이미 실행 중입니다."
  fi
  if port_in_use 5173; then
    echo "  - 5173번 포트: React/Vite가 이미 실행 중입니다."
  fi
  echo "기존 실행 창에서 Ctrl+C로 종료한 뒤 다시 실행해 주세요."
  exit 1
fi

BACKEND_PID=""
FRONTEND_PID=""
SHUTDOWN_REQUESTED=0

cleanup() {
  SHUTDOWN_REQUESTED=1
  trap - EXIT INT TERM

  if [[ -n "$BACKEND_PID" ]]; then
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
  if [[ -n "$FRONTEND_PID" ]]; then
    kill "$FRONTEND_PID" 2>/dev/null || true
  fi

  wait "$BACKEND_PID" 2>/dev/null || true
  wait "$FRONTEND_PID" 2>/dev/null || true
}

trap cleanup EXIT INT TERM

echo "FastAPI:  http://localhost:8000"
"$BACKEND_RUNNER" app.main:app \
  --app-dir "$PROJECT_DIR/backend" \
  --reload-dir "$PROJECT_DIR/backend" \
  --host 0.0.0.0 \
  --port 8000 \
  --reload &
BACKEND_PID=$!

echo "로컬 주소: http://localhost:5173"
echo "도메인:    http://${APP_DOMAIN}:5173"
(
  cd "$FRONTEND_DIR"
  npm run dev -- --host 0.0.0.0
) &
FRONTEND_PID=$!

echo "종료하려면 Ctrl+C를 누르세요."

set +e
wait -n "$BACKEND_PID" "$FRONTEND_PID"
STATUS=$?
set -e

if [[ "$SHUTDOWN_REQUESTED" -eq 0 ]]; then
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo "FastAPI 서버가 예기치 않게 종료되었습니다. 위 오류 내용을 확인해 주세요."
  fi
  if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
    echo "React/Vite 서버가 예기치 않게 종료되었습니다. 위 오류 내용을 확인해 주세요."
  fi
fi

exit "$STATUS"
