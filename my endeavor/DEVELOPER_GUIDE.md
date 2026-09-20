# K-MAX 개발자 가이드

이 문서는 현재 저장소의 **실제 코드 동작**을 기준으로 K-MAX 프로토타입의 구조, 실행 흐름, 데이터 저장 방식, 주요 API와 유지보수 시 주의점을 정리한다.

## 1. 프로젝트 한눈에 보기

K-MAX는 고령 사용자를 위한 웹 기반 건강 확인 프로토타입이다. 화면에 표시되는 AI 건강 동반자의 이름은 **동행이**다.

- 프론트엔드: React 18 + Vite + Tailwind CSS
- 백엔드: FastAPI + Pydantic
- 영상 분석: 브라우저에서 MediaPipe Tasks Vision 실행
- 대화 생성: Gemini API, 미설정 시 로컬 규칙 기반 fallback
- 음성 입력: 브라우저 `MediaRecorder` → Whisper 전사
- 저장소: 별도 DB 없이 `backend/data/` 아래 JSON 파일 사용
- 자동 실행: 서버 로컬 시간 기준 08·10·12·14·16·18·20시

카메라의 원본 영상과 얼굴 이미지는 서버로 전송하지 않는다. 브라우저가 영상에서 추출하고 평균 낸 landmark 좌표만 백엔드에 전달한다. 음성 원본도 전사 과정의 임시 파일로만 사용하며 영구 저장하지 않는다.

## 2. 전체 구조

```text
브라우저
  App.jsx
    ├─ MediaPipe Pose/Face Landmarker (브라우저 추론)
    ├─ Web Speech API (동행이 메시지 읽기)
    ├─ MediaRecorder (사용자 음성 녹음)
    └─ /api 요청
          ↓ Vite proxy
FastAPI (backend/app/main.py)
    ├─ pose_tool.py / face_tool.py       측정 검증 및 특징 계산
    ├─ pose_store.py                     기준값 비교와 측정 이력
    ├─ scheduler.py                      정시 이벤트 발행
    ├─ conversation.py                   대화 상태와 FAST 확인
    ├─ stroke_screening.py               고정 규칙 기반 위험 신호 선별
    ├─ audio_tool.py                     local/OpenAI Whisper 전사
    ├─ chat.py                            일반 채팅
    └─ agent.py                           Tool 평가 API(현재 UI 미연결)
          ↓
backend/data/*.json
```

### 주요 파일

| 경로 | 역할 |
|---|---|
| `frontend/src/App.jsx` | 화면, 루틴 상태, 카메라·마이크 제어, API 호출을 한 컴포넌트에서 관리 |
| `frontend/src/poseLandmarker.js` | Pose 모델 초기화, 여러 프레임 평균, 화면 skeleton 그리기 |
| `frontend/src/faceLandmarker.js` | Face 모델 초기화, 여러 프레임 평균, landmark 안정성 계산 |
| `frontend/public/models/` | 브라우저에서 로드하는 MediaPipe 모델 파일 |
| `backend/app/main.py` | FastAPI 앱 생성과 모든 HTTP endpoint 등록 |
| `backend/app/pose_tool.py` | 자세 입력 품질 검사와 팔 각도·높이 비대칭 계산 |
| `backend/app/face_tool.py` | 얼굴 입력 품질 검사와 입꼬리·코 중심 등 계산 |
| `backend/app/pose_store.py` | 자세/얼굴 baseline, 일별 측정 이력, baseline 비교 |
| `backend/app/scheduler.py` | 고정 시각 스케줄과 이벤트 중복 claim 방지 |
| `backend/app/conversation.py` | 대화 생성, turn 저장, 후속 질문/종료 처리 |
| `backend/app/stroke_screening.py` | 측정 변화와 사용자 문장을 조합한 FAST 위험 신호 규칙 |
| `backend/app/audio_tool.py` | 오디오 검증, ffmpeg 변환, Whisper 실행 |
| `backend/app/agent.py` | Gemini function calling 또는 규칙 기반 Tool 평가 |
| `backend/app/prompts.py`, `prompt.txt` | Agent 공통 prompt와 실제 권한 제한 |
| `start.sh` | 백엔드와 프론트엔드를 함께 실행하고 종료 처리 |

## 3. 실행 방법

### 최초 설치

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
cd frontend && npm install && cd ..
cp .env.example .env
```

`.env`에서 필요한 키와 음성 전사 방식을 설정한다. 로컬 Whisper를 쓸 경우 최초 한 번 다음을 실행한다.

```bash
bash scripts/setup_local_whisper.sh
```

이 스크립트 외에도 로컬 전사에는 `ffmpeg`가 필요하다.

### 통합 실행

```bash
bash start.sh
```

- 프론트엔드: `http://localhost:5173`
- 백엔드: `http://localhost:8000`
- Swagger UI: `http://localhost:8000/docs`
- 같은 LAN의 다른 기기: 기본적으로 `http://<장치명>.local:5173`

`start.sh`는 `.env`, `.env.local` 순서로 환경 변수를 읽는다. 8000 또는 5173 포트가 이미 사용 중이면 실행을 중단하며, `Ctrl+C`를 누르면 두 프로세스를 함께 종료한다.

### 개별 실행

```bash
.venv/bin/uvicorn app.main:app --app-dir backend --reload
```

```bash
cd frontend
npm run dev
```

Vite가 `/api`를 `http://localhost:8000`으로 proxy하므로 프론트엔드 코드는 백엔드 호스트를 직접 지정하지 않는다.

## 4. 애플리케이션 실행 흐름

### 시작 시

1. `App.jsx`가 자세 baseline과 얼굴 baseline을 각각 조회한다.
2. 자세 또는 얼굴 baseline이 준비되지 않았으면 `최초 개인 기준 등록` 카드를 표시한다.
3. 사용자가 등록을 시작하면 자세와 얼굴을 각각 3회 수집하며, 일부 샘플이 있으면 남은 횟수만 진행한다.
4. 브라우저 `localStorage`에 진행 중인 대화가 있으면 화면에 복원한다.
5. 15초마다 scheduler 상태를 조회한다.
6. 이벤트가 due 상태이면 `/api/scheduler/claim`으로 한 번만 가져온다.
7. claim한 시각에 따라 오전 루틴 또는 주기 루틴을 시작한다.

브라우저는 마지막으로 표시한 event ID를 `health-agent-last-scheduler-event`에 저장해 같은 브라우저에서 중복 표시하지 않는다. 진행 중인 대화는 `health-agent-active-conversation`에 저장한다.

### 08시 오전 루틴

```text
Pose 측정
  ├─ 측정 실패: 최대 3회 재시도 후 종료
  ├─ baseline 대비 유의 변화 없음: 종료
  └─ baseline 대비 유의 변화 있음
       → Face 측정
       → 대화 시작
       → 측정 변화가 FAST 대상이면 고정 증상 확인 질문
```

따라서 UI의 시연 설명과 달리 현재 실제 코드는 정상 Pose 결과일 때 얼굴·대화를 항상 실행하지 않는다. 자세 변화가 감지될 때만 얼굴과 대화로 이어진다.

### 10·12·14·16·18·20시 주기 루틴

```text
일상 대화/음성 확인
  ├─ 추가 확인 불필요: 종료
  ├─ 긴급 증상 확인: 119 안내 overlay 표시 후 종료
  └─ 문맥 연결 문제가 누적됨
       → Face 측정
       → Pose 측정
       → 종료
```

대화 첫 질문은 Gemini가 생성한다. 키가 없으면 `LocalConversationGenerator`의 고정 질문 세 개를 순환한다. 서버는 첫 응답 후 일반적으로 “더 들려주실 말씀이 있는지” 한 번 더 묻고, 사용자의 종료 표현 또는 후속 녹음의 무음으로 대화를 마친다.

### 일반 채팅

루틴 대화가 진행 중이면 입력 내용을 `/api/conversation/respond`로 보낸다. 그 외에는 `/api/chat`으로 보낸다. Gemini 키가 없을 때 일반 채팅은 고정 fallback 응답을 돌려준다.

## 5. 영상 측정 처리

### 공통 브라우저 처리

- 카메라는 `getUserMedia`로 연다.
- 10초 countdown 뒤 약 140ms 간격으로 8개 프레임을 읽는다.
- landmark를 좌표별 평균 내어 한 요청으로 전송한다.
- 실패하면 다시 10초 countdown을 거쳐 최대 3회 시도한다.
- 컴포넌트 종료, 취소 또는 run ID 변경 시 이전 비동기 측정 결과를 무시한다.

### Pose

`pose_tool.stretch_check()`는 33개 landmark 중 어깨·팔꿈치·손목(11~16)을 사용한다.

- 최소 검출 프레임: 3개이며 검출률 60% 이상
- 필수 landmark visibility: 각각 0.55 이상
- 최종 품질: 0.65 이상
- 프레임 종횡비를 복원한 뒤 양쪽 팔꿈치 각도를 계산
- 양팔 각도 차이, 팔 높이, 손목 높이 차이 등을 반환

### Face

`face_tool.face_check()`는 코, 눈·입 양 끝, 이마, 턱, 양 볼 등 지정 landmark를 사용한다.

- 검출률 50% 이상
- landmark 안정성 0.55 이상
- 최종 품질 0.55 이상
- 얼굴이 프레임 안에 있고 충분히 크며 정면에 가까운지 확인
- 눈의 기울기로 head roll을 보정한 후 입꼬리 기울기, 코 중심 편차 등을 반환
- baseline 샘플로 저장할 때는 측정 성공 기준보다 엄격한 품질 0.65 이상이 필요

## 6. 개인 baseline과 변화 판정

자세와 얼굴 baseline은 각각 첫 3개의 성공한 고품질 실제 측정으로 준비된다. 최초 실행 시 둘 중 하나라도 준비되지 않았으면 별도의 등록 카드가 나타나며, 사용자의 시작 동의 후 `자세 3회 → 얼굴 3회` 순서로 등록한다. 이미 1~2개가 저장되어 있으면 남은 횟수만 수행하고, 중간에 측정이 실패하면 무한 반복하지 않고 등록을 중단한 뒤 `개인 기준 등록 계속` 버튼으로 재개한다.

백엔드는 최대 20개 샘플을 유지할 수 있지만, 현재 프론트엔드는 3개가 모여 `ready`가 된 이후 자동 샘플 추가를 중단한다.

비교 허용 범위는 다음 식을 사용한다.

```text
tolerance = max(기능별 최소 허용값, baseline 표준편차 × 3)
changed = |현재값 - baseline 평균| > tolerance
```

자세의 팔 각도/높이/손목 차이와 얼굴의 입꼬리/코 중심/입-눈 거리만 비교 대상으로 사용한다. 뇌졸중 선별 신호에는 그중 다음 항목만 사용한다.

- Pose: `arm_angle_difference`, `wrist_height_difference`
- Face: `mouth_tilt`

머리 방향, 코 위치, 측정 실패 자체는 긴급 신호로 사용하지 않는다.

## 7. 대화와 안전 선별

안전 관련 최종 판단은 Gemini가 아니라 `stroke_screening.py`의 고정 규칙이 담당한다.

1. baseline 대비 대상 비대칭이 있으면 일반 질문 대신 고정 FAST 확인 질문을 제시한다.
2. 사용자의 답변에서 한쪽 얼굴 처짐, 한쪽 팔·다리 힘 빠짐, 말하기/이해하기 어려움, 갑작스러운 균형·시야 이상, 갑작스러운 심한 두통 표현을 찾는다.
3. 명시적 긍정 또는 증상 문구가 있으면 대화를 끝내고 즉시 119 연락을 안내한다.
4. 불명확하면 “있어요/없어요”로 다시 답하도록 한 번 더 확인한다.

이 기능은 진단 기능이 아니다. 실제 119 전화, 문자, 보호자 연락 기능도 구현되어 있지 않다. 화면의 긴급 overlay는 30초 뒤 사라지지만 대화 기록의 `urgent_alert` 값은 저장된다.

## 8. 음성 처리

1. 대화가 음성 입력을 요청하면 질문 표시 약 0.8초 뒤 녹음을 자동 시작한다.
2. 첫 질문은 최대 30초, 후속 질문은 최대 15초 녹음한다.
3. Web Audio API로 단순 RMS 음성 감지를 병행한다.
4. 녹음 blob을 multipart 형식으로 `/api/audio/transcribe`에 보낸다.
5. local backend는 임시 디렉터리에서 ffmpeg로 16kHz mono WAV 변환 후 `whisper-cli`를 실행한다.
6. 성공한 음성 transcript와 duration은 사용자가 대화 응답으로 제출될 때만 대화 JSON에 저장한다.

후속 질문에서 무음 또는 너무 짧은 입력이 감지되면 대화를 자연스럽게 종료한다. 사용자가 녹음 중 텍스트를 보내면 진행 중 음성을 폐기하고 텍스트 입력을 우선한다.

## 9. 주요 API

| Method | 경로 | 설명 |
|---|---|---|
| GET | `/api/health` | 서버, Gemini, 전사 backend 설정 상태 |
| GET/POST | `/api/items` | 초기 샘플용 범용 JSON 배열 저장 API |
| POST | `/api/tools/stretch-check` | Pose 품질/특징 계산, baseline 비교, 이력 저장 |
| POST | `/api/tools/face-check` | Face 품질/특징 계산, baseline 비교, 이력 저장 |
| GET | `/api/pose/baseline` | 자세 baseline 요약 |
| POST | `/api/pose/baseline/samples` | 자세 baseline 샘플 추가 |
| GET | `/api/face/baseline` | 얼굴 baseline 요약 |
| POST | `/api/face/baseline/samples` | 얼굴 baseline 샘플 추가 |
| GET | `/api/scheduler/status` | 현재 due 상태와 다음 예약 시각 |
| POST | `/api/scheduler/claim` | due 이벤트를 원자적으로 한 번 claim |
| POST | `/api/conversation/start` | event ID 기준 대화 생성/복원 |
| POST | `/api/conversation/respond` | 텍스트/전사 응답 처리 |
| POST | `/api/conversation/timeout` | 응답 없이 대화 종료 |
| POST | `/api/audio/transcribe` | multipart 음성 전사 |
| POST | `/api/chat` | 루틴 외 일반 채팅 |
| POST | `/api/agent/evaluate` | 측정 Tool 결과에 대한 Agent 판단 |

정확한 request/response schema는 서버 실행 후 `/docs`에서 확인하는 것이 가장 빠르다.

## 10. 저장 데이터

```text
backend/data/
  baseline/
    pose_baseline.json       자세 샘플과 통계
    face_baseline.json       얼굴 샘플과 통계
  history/YYYY-MM-DD.json    해당 날짜의 자세·얼굴 측정 결과
  scheduler/state.json       마지막 claim 시각과 event ID
  conversations/
    index.json               event ID → 대화 파일 경로
    YYYY-MM-DD/<id>.json     질문, turn, transcript, 안전 상태
  items.json                 범용 items API 데이터
```

JSON 쓰기는 같은 디렉터리의 임시 파일을 작성한 뒤 `replace`하는 방식으로 원자성을 확보한다. 프로세스 내부 동시 접근은 `threading.Lock`으로 막지만, 여러 백엔드 프로세스가 같은 데이터 디렉터리를 공유하는 배포는 지원하지 않는다.

운영/테스트 데이터를 초기화할 때는 서버를 먼저 중지하고 필요한 JSON을 백업해야 한다. 특히 baseline의 `samples`와 `summary`는 서로 일치해야 한다.

## 11. 환경 변수

| 변수 | 용도 | 코드 기본값/비고 |
|---|---|---|
| `GEMINI_API_KEY` | Agent, 대화, 일반 채팅의 Gemini 활성화 | 없으면 local fallback |
| `GEMINI_MODEL` | Gemini 모델 | 코드 기본값 `gemini-2.5-flash`; `.env.example` 값이 있으면 그것이 우선 |
| `WHISPER_BACKEND` | `local` 또는 `openai` | 코드 자체 기본값은 `openai`; `.env.example`은 `local` |
| `OPENAI_API_KEY` | OpenAI Whisper 사용 시 필요 | local에는 불필요 |
| `OPENAI_TRANSCRIBE_MODEL` | OpenAI 전사 모델 | `whisper-1` |
| `WHISPER_CPP_BINARY` | 로컬 whisper 실행 파일 | `.local/whisper.cpp/.../whisper-cli` |
| `WHISPER_CPP_MODEL` | 로컬 whisper 모델 | `ggml-small-q5_1.bin` |
| `WHISPER_LOCAL_TIMEOUT_SECONDS` | 로컬 전사 제한 시간 | 120초 |
| `APP_DOMAIN` | Vite가 허용할 LAN host | `<hostname>.local` |

`.env.example`에 있는 `CHECK_INTERVAL_SECONDS`는 **현재 scheduler 코드에서 읽지 않는다**. 현재 주기는 환경 변수 기반 간격이 아니라 `SCHEDULE_HOURS = (8, 10, 12, 14, 16, 18, 20)`로 고정되어 있다.

## 12. 테스트와 검증

```bash
.venv/bin/python -m unittest discover -s backend/tests -v
cd frontend && npm run build
```

백엔드 테스트는 Pose/Face 계산, baseline 저장·비교, Agent 판단, scheduler, 대화, 음성 입력 검증, 안전 선별과 통합 시나리오를 다룬다. 프론트엔드는 별도 unit test가 없으므로 build와 실제 브라우저 장치 테스트가 필요하다.

수동 확인 권장 항목:

- 카메라와 마이크 권한 허용/거부 처리
- localhost와 `.local` 주소에서 secure context 충족 여부
- Pose/Face 모델 최초 로딩과 WebGL 미지원 처리
- 8시/14시 시연 버튼의 전체 루틴
- Gemini 키 유무에 따른 fallback
- local Whisper 설치 여부와 ffmpeg 실행
- 서버 재시작 후 scheduler 중복 claim 및 대화 복원
- baseline 3개 수집 전/후의 분기

## 13. 유지보수 시 꼭 알아둘 점

1. **현재 화면은 `/api/agent/evaluate`를 호출하지 않는다.** `App.jsx`가 Pose 결과의 `significant_change`를 직접 보고 다음 단계를 결정한다. `agent.py`는 API와 테스트에는 존재하지만 실제 UI 루틴에는 연결되어 있지 않다.
2. **스케줄은 간격 기반이 아니다.** `CHECK_INTERVAL_SECONDS`를 바꿔도 동작이 변하지 않는다. 개발용 시간을 바꾸려면 `scheduler.py`의 `SCHEDULE_HOURS` 또는 clock을 주입한 테스트를 사용한다.
3. **서버 timezone이 곧 스케줄 timezone이다.** 별도로 Asia/Seoul을 강제하지 않고 `datetime.now().astimezone()`을 사용한다.
4. **예약 이벤트 claim 가능 시간은 정시 후 15분이다.** 그 이후 시작한 서버는 지난 이벤트를 소급 실행하지 않는다.
5. **프론트 상태 관리가 `App.jsx` 한 파일에 집중되어 있다.** 루틴을 확장할 때는 상태 전이, 비동기 run ID, 카메라/마이크 정리 로직을 함께 수정해야 한다.
6. **대화 idempotency 기준은 event ID다.** 같은 event ID로 `/conversation/start`를 다시 호출하면 기존 대화를 반환한다.
7. **여러 worker를 사용하면 JSON lock이 공유되지 않는다.** 현재 저장 방식은 단일 FastAPI 프로세스를 전제로 한다.
8. **`prompt.txt`는 모듈 import 시 읽힌다.** 수정 후 백엔드를 재시작해야 Agent에 안정적으로 반영된다.
9. **의료 안전 규칙 변경은 생성형 prompt만 수정해서는 안 된다.** 실제 긴급 분기는 `stroke_screening.py`와 `conversation.py`에 있으므로 테스트와 함께 변경해야 한다.
10. **실제 외부 연락 기능은 없다.** UI 문구나 prompt에서 전화·문자 전송이 완료된 것처럼 표현하면 안 된다.

## 14. 기능 변경 체크리스트

- 새 측정 feature 추가: Tool 반환 모델 → baseline feature 목록/허용치 → 저장 JSON → 안전 선별 → 테스트 순으로 확인
- 새 API 추가: Pydantic schema와 endpoint 작성 후 `/docs`, 오류 status code, 프론트 fetch 처리 확인
- 새 루틴 단계 추가: `routineStage`와 ref를 동시에 갱신하고 취소 시 stream/timer/run ID 정리
- 전사 backend 변경: `/api/health`의 configured 상태와 실제 샘플 파일 전사를 함께 확인
- scheduler 변경: 중복 claim, grace window, 자정 경계, timezone 테스트 추가
- 안전 문구 변경: 진단 표현 금지, 사용자 확인 우선, 자동 연락 미지원 문구 유지
