# FastAPI + React 테스트 프로젝트

추후 전달할 프로젝트 명세를 적용하기 전의 최소 개발 구조입니다.

전체 실행·구조·데이터·제한 사항은 [PROGRAM_GUIDE.md](PROGRAM_GUIDE.md)를 참고하세요.

## 구조

```text
backend/
  app/             FastAPI 애플리케이션
  data/items.json  JSON 데이터 저장소
frontend/
  src/             React 애플리케이션
```

## 백엔드 실행

프로젝트 루트에서 다음 명령을 실행합니다.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
uvicorn app.main:app --reload --app-dir backend
```

백엔드는 `http://localhost:8000`, API 문서는 `http://localhost:8000/docs`에서 열립니다.

## 프론트엔드 실행

별도 터미널에서 다음 명령을 실행합니다.

```bash
cd frontend
npm install
npm run dev
```

프론트엔드는 `http://localhost:5173`에서 열립니다. 개발 서버가 `/api` 요청을 백엔드로 전달합니다.

## 기본 API

- `GET /api/health`: 서버 상태 확인
- `GET /api/items`: `backend/data/items.json` 읽기
- `POST /api/items`: JSON 배열 전체 저장

## Gemini Agent 설정

`.env.example`을 `.env`로 복사하고 `GEMINI_API_KEY`를 입력하면 중앙 Agent가
Gemini function calling을 사용합니다. 키가 없을 때는 화면과 측정 흐름을 시험할
수 있도록 동일한 응답 계약의 로컬 fallback이 동작합니다.

```bash
cp .env.example .env
# .env 파일의 GEMINI_API_KEY 값을 입력
bash start.sh
```

실행하면 로컬 주소와 함께 장치 이름을 이용한 도메인 주소도 표시됩니다.

```text
로컬 주소: http://localhost:5173
도메인:    http://raspberrypi.local:5173
```

다른 도메인을 사용할 때는 `.env.local`에 프로토콜 없이 호스트 이름을 지정합니다.

```bash
APP_DOMAIN=health-companion.local
```

`.local` 주소는 같은 네트워크에서 mDNS를 지원하는 기기에서 사용할 수 있습니다.

- `POST /api/agent/evaluate`: Tool 결과를 Agent가 평가하고 다음 행동 반환
- `GET /api/health`: 서버 상태와 Gemini 설정 여부 확인

## 주기적 확인 Scheduler

첫 정상 자세 측정이 완료되면 주기적 대화 확인 시간이 예약됩니다. 기본 주기는
4시간이며 JSON 상태가 `backend/data/scheduler/state.json`에 저장되므로 앱을
재시작해도 중복 이벤트가 생성되지 않습니다.

개발 중 1분 주기로 시험하려면 `.env`에서 다음 값을 설정한 뒤 서버를
재시작합니다.

```bash
CHECK_INTERVAL_SECONDS=60
```

- `GET /api/scheduler/status`: 다음 확인 시각과 남은 시간
- `POST /api/scheduler/claim`: 예정된 이벤트를 한 번만 가져오기

## 주기적 대화 시작

Scheduler 이벤트가 발생하면 Gemini가 최근 대화 기록을 참고해 일상적인 질문을
먼저 생성합니다. 동일 이벤트 ID에는 저장된 질문을 재사용하며, 사용자 답변이
짧거나 불명확할 때만 후속 질문을 한 번 요청합니다.

- `POST /api/conversation/start`: 이벤트 ID로 대화 시작 또는 기존 질문 복원
- `POST /api/conversation/respond`: 사용자 답변 전달 및 후속 행동 반환
- `POST /api/chat`: 대화 중이 아닐 때도 일반 채팅을 Gemini에게 전달

대화 JSON은 `backend/data/conversations/YYYY-MM-DD/`에 저장됩니다. 현재 답변은
텍스트 입력 또는 질문 시 활성화되는 마이크 입력으로 진행합니다.

자세 기준 데이터는 성공한 실제 카메라 측정에서 자동으로 수집되며, 처음 3개 샘플이
개인 기준으로 활성화됩니다. 수동 기준값 입력은 사용하지 않습니다.

## Whisper 음성 전사

기본 설정은 서버에서 `whisper.cpp`를 직접 실행하므로 OpenAI API 크레딧이 필요하지
않습니다. 최초 한 번 `bash scripts/setup_local_whisper.sh`를 실행하면 ARM64에 맞춰
CLI를 빌드하고 한국어용 `small-q5_1` 모델을 내려받습니다. 브라우저의 WebM/Opus
녹음은 ffmpeg로 16kHz mono WAV로 변환한 뒤 로컬 모델로 전사합니다. 원본 오디오는
임시 디렉터리에서 처리 후 삭제하며, 성공한 transcript와 duration만 저장합니다.

OpenAI 전사로 되돌리려면 `.env.local`의 `WHISPER_BACKEND`를 `openai`로 바꾸고
`.env`에 `OPENAI_API_KEY`를 설정합니다.

- 마이크 버튼은 대화가 진행 중일 때만 표시됩니다.
- 최대 녹음 시간은 30초입니다.
- `POST /api/audio/transcribe`: multipart 오디오 전사 API
- 짧은 발화, 무음, 미지원 형식, API 오류는 구조화된 재시도 오류로 반환됩니다.

## Face Tool

Agent가 필요하다고 판단할 때 사용할 수 있는 얼굴 특징점 분석 API입니다.
브라우저에서 전달한 Face Landmarker 좌표의 품질, 눈·입 기울기, 코 중심 편차를
계산하고 선택적으로 기준값과의 변화를 반환합니다. 현재 음성 Tool은 비활성화되어
Agent가 요청할 수 있는 Tool 목록에서도 제외되어 있습니다.

- `POST /api/tools/face-check`: 얼굴 특징점 분석

## 뇌졸중 위험 신호 선별

이 기능은 뇌졸중을 진단하지 않습니다. 자세·얼굴 측정은 개인 기준과 달라진 좌우
비대칭을 찾는 보조 신호로만 사용합니다. 팔 높이/각도 비대칭 또는 입꼬리 기울기
변화가 있으면 고정된 FAST 확인 질문을 먼저 제시합니다. 머리 방향이나 코 위치
변화, 측정 실패, 전사 오류만으로는 긴급 경고를 만들지 않습니다.

사용자가 한쪽 얼굴 처짐, 한쪽 팔·다리 힘 빠짐, 말하기·이해하기 어려움 또는
갑작스러운 균형·시야 이상을 확인하면 즉시 119 연락을 안내합니다. 카메라 수치나
AI 응답 단독으로 질환을 확정하지 않으며 실제 문자·전화는 현재 구현되어 있지
않습니다.
