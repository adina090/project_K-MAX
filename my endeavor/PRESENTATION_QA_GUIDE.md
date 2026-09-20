# K-MAX 발표 및 질의응답 가이드

이 문서는 K-MAX 프로젝트를 발표하는 사람이 코드를 전부 외우지 않고도 **각 파일의 역할, 핵심 동작, 파일 사이의 연결 관계**를 설명할 수 있도록 정리한 자료다. 설명은 현재 실행되는 코드를 기준으로 한다.

## 1. 발표 시작 때 사용할 한 문장

> K-MAX는 브라우저에서 자세와 얼굴 특징점을 분석하고, 개인별 기준값과 비교하며, 정해진 시간의 대화와 음성 전사를 결합해 건강 이상 징후를 보조적으로 확인하는 FastAPI·React 기반 프로토타입입니다.

중요한 표현은 **진단**이 아니라 **보조적 확인**이다. 이 프로그램은 뇌졸중을 판정하지 않으며, 실제 전화나 보호자 문자도 전송하지 않는다.

## 2. 1분 안에 설명하는 전체 동작

```text
예약 시간 도착
   ↓
브라우저가 Scheduler 이벤트 확인
   ↓
08시: 자세부터 시작       그 외 시간: 대화부터 시작
   ↓                       ↓
MediaPipe가 브라우저에서 landmark 추출
   ↓
FastAPI가 품질 검사·특징 계산·개인 baseline 비교
   ↓
필요할 때 얼굴/자세/대화를 추가 확인
   ↓
고정 안전 규칙이 사용자 증상 표현 확인
   ↓
정상 종료 또는 119 연락 안내
```

발표할 때 강조할 세 가지:

1. 영상 AI는 서버가 아니라 **사용자 브라우저에서 실행**된다.
2. 현재 측정값을 절대 기준으로 판정하지 않고 **개인 baseline과 비교**한다.
3. 긴급 안내는 생성형 AI의 자율 판단이 아니라 **서버의 고정 규칙**이 최종 결정한다.

## 3. 폴더 단위 역할

| 폴더 | 쉬운 설명 | 들어 있는 것 |
|---|---|---|
| `frontend/` | 사용자가 보는 화면과 장치 제어 | React UI, 카메라, MediaPipe, 녹음 |
| `backend/app/` | 측정 결과를 계산하고 흐름을 판단하는 서버 | FastAPI, baseline, 대화, 안전 규칙 |
| `backend/tests/` | 핵심 동작이 망가지지 않았는지 확인 | 현재 71개 단위·통합 테스트 |
| `backend/data/` | DB 대신 사용하는 실행 데이터 | baseline, 측정 이력, 대화, scheduler 상태 |
| `scripts/` | 개발 환경 준비 자동화 | 로컬 Whisper 설치 스크립트 |
| `my endeavor/` | 요구사항·설계·개발자 문서 | 실행에는 직접 사용되지 않는 문서 |

## 4. 프론트엔드 파일

### `frontend/src/App.jsx` — 전체 화면과 루틴의 지휘자

발표용 한 문장:

> App.jsx는 화면 표시뿐 아니라 Scheduler polling, 카메라 측정, 음성 녹음, 대화 전송, 단계 전환을 모두 관리하는 프론트엔드의 중심 파일입니다.

핵심 기능:

- 앱 시작 시 자세/얼굴 baseline을 서버에서 불러온다.
- baseline이 없거나 3개 미만이면 최초 개인 기준 등록 카드를 표시한다.
- 사용자의 시작 동의 후 자세와 얼굴을 각각 3회 등록하며 기존 샘플이 있으면 남은 횟수만 측정한다.
- 15초마다 `/api/scheduler/status`를 조회한다.
- due 이벤트를 `/api/scheduler/claim`으로 가져와 루틴을 시작한다.
- 오전 루틴과 주기 루틴의 순서를 결정한다.
- 카메라와 마이크 권한, stream, timer를 관리한다.
- MediaPipe 결과를 측정 API로 전송한다.
- 대화 중에는 음성과 텍스트 중 먼저 확정된 입력을 처리한다.
- 서버 메시지를 브라우저 Speech Synthesis로 읽어 준다.
- 긴급 응답이면 119 안내 overlay를 표시한다.
- 진행 중인 대화를 `localStorage`에 저장하고 새로고침 뒤 복원한다.

중요 상수:

- `SAMPLE_COUNT = 8`: 한 번의 측정에서 8개 프레임 수집
- `MAX_RETRIES = 3`: 영상 측정 최대 세 번 시도
- `POSE_COUNTDOWN_SECONDS = 10`: 측정 전 10초 준비 시간
- `VOICE_MAX_RECORDING_SECONDS = 30`: 첫 음성 녹음 최대 30초

중요 함수:

| 함수 | 하는 일 |
|---|---|
| `launchScheduledRoutine()` | 시각이 8시면 오전 루틴, 아니면 주기 루틴 선택 |
| `measurePose()` | 카메라 준비 → countdown → 8프레임 수집 → Pose API 호출 → 다음 단계 선택 |
| `measureFace()` | Face landmark 수집과 API 호출, 실패 재시도 |
| `startFixedConversation()` | event ID와 측정 문맥으로 대화 시작 |
| `submitConversationResponse()` | 텍스트 또는 전사 결과를 대화 서버로 전달 |
| `startVoiceRecording()` | `MediaRecorder`로 녹음하고 RMS로 음성 존재 여부 확인 |
| `uploadVoiceRecording()` | 녹음 파일을 전사 API에 전송 |
| `completeConversationRoutine()` | 추가 영상 확인 또는 루틴 종료 결정 |
| `stopCamera()` | 실행 ID를 무효화하고 stream·측정을 안전하게 중단 |

알아둘 한계:

- 화면과 업무 로직이 한 파일에 몰려 있어 기능 확장 시 복잡도가 커진다.
- 현재 `App.jsx`는 `/api/agent/evaluate`를 호출하지 않는다. Pose 변화 여부를 프론트 코드가 직접 판단한다.
- 우측 8시 시연 버튼 설명은 `자세 → 표정 → 음성`이지만, 실제로는 정상 자세이면 얼굴과 대화 없이 종료될 수 있다.

### `frontend/src/poseLandmarker.js` — 자세 AI 모델 어댑터

발표용 한 문장:

> MediaPipe Pose 모델을 한 번만 초기화하고, 여러 프레임의 관절 좌표를 평균 내는 파일입니다.

핵심 기능:

- `/models/pose_landmarker_lite.task` 모델을 `VIDEO` 모드로 로드한다.
- 한 사람만 인식하며 detection/presence/tracking confidence를 0.5로 둔다.
- `averageLandmarks()`가 여러 프레임의 x·y·z·visibility를 평균 낸다.
- `drawPose()`는 video의 `object-cover` 비율에 맞춰 skeleton을 canvas에 그릴 수 있다.

주의할 점: 현재 `drawPose()`는 정의되어 있지만 `App.jsx`에서 호출하지 않는다. 즉, skeleton overlay 기능을 준비했지만 현재 화면에는 연결되지 않았다.

### `frontend/src/faceLandmarker.js` — 얼굴 AI 모델 어댑터

발표용 한 문장:

> 얼굴 특징점 모델을 실행하고, 좌표 평균과 프레임 간 흔들림을 계산해 측정 신뢰도를 높이는 파일입니다.

핵심 기능:

- `/models/face_landmarker.task`를 로드하고 얼굴 한 개를 추적한다.
- `averageFaceLandmarks()`가 여러 프레임을 평균 낸다.
- `faceLandmarkStability()`가 코·눈·입 주변 5개 점의 흔들림을 눈 사이 거리로 정규화한다.
- 안정성 결과는 0~1 범위이며 서버의 품질 계산에 사용된다.

### `frontend/src/main.jsx` — React 시작점

`index.html`의 `root` 요소에 `<App />`을 렌더링하고 공통 CSS를 불러온다. `React.StrictMode`도 여기서 적용한다.

### `frontend/src/index.css` — 전역 스타일

Tailwind의 base/components/utilities를 활성화한다. 기본 글자 크기를 18px로 높이고 줄 간격을 넓혀 고령 사용자의 가독성을 고려한다. `pulse-ring` 애니메이션도 정의한다.

### `frontend/index.html` — HTML 껍데기

한국어 문서, viewport, 브라우저 제목, React가 들어갈 `<div id="root">`를 선언한다.

### `frontend/vite.config.js` — 개발 서버 연결 설정

핵심 기능:

- Vite를 모든 네트워크 인터페이스의 5173 포트에서 실행한다.
- `APP_DOMAIN` 또는 `<장치명>.local` 접속을 허용한다.
- `/api` 요청을 `localhost:8000`의 FastAPI로 proxy한다.

따라서 프론트 코드에 백엔드 URL이 하드코딩되지 않는다.

### `frontend/tailwind.config.js`, `postcss.config.js`

- `tailwind.config.js`: Tailwind가 class 이름을 찾을 파일 범위를 지정한다.
- `postcss.config.js`: 빌드 시 Tailwind와 Autoprefixer를 실행한다.

### `frontend/package.json`, `package-lock.json`

- `package.json`: React, MediaPipe, Lucide 아이콘, Vite, Tailwind 의존성과 `dev/build/preview` 명령을 정의한다.
- `package-lock.json`: 실제 설치 버전을 고정해 다른 환경에서도 같은 의존성 조합을 재현한다.

### `frontend/public/models/`

- `pose_landmarker_lite.task`: 자세 추론 모델
- `face_landmarker.task`: 얼굴 특징점 추론 모델

정적 파일이므로 Vite가 `/models/...` 주소로 그대로 제공한다. 모델 추론은 클라이언트 장치의 CPU/WebAssembly 또는 브라우저 실행 환경을 사용한다.

### `frontend/README.md`

초기 프론트엔드 실행 안내다. 현재 전체 시스템 설명은 부족하므로 발표에서는 `DEVELOPER_GUIDE.md`와 이 문서를 우선한다.

### `frontend/dist/`, `frontend/node_modules/`

- `dist/`: `npm run build`로 생성되는 배포 결과물이다. 직접 수정하지 않는다.
- `node_modules/`: npm이 설치한 외부 패키지다. 직접 수정하거나 발표에서 개별 파일을 설명할 필요가 없다.

## 5. 백엔드 실행 파일

### `backend/app/main.py` — API 입구

발표용 한 문장:

> main.py는 각 기능 모듈을 FastAPI endpoint로 연결하고, 앱 시작 시 서비스 객체를 생성하는 서버의 진입점입니다.

앱 시작 시 생성하는 객체:

- `PoseDataStore`: baseline과 측정 이력 관리
- `AgentOrchestrator`: 측정 결과 Agent 판단
- `PeriodicScheduler`: 예약 이벤트 관리
- `ConversationService`: 대화 생성과 저장
- `AudioTranscriptionService`: 음성 전사 backend 선택

중요 endpoint 그룹:

- 상태: `/api/health`
- 측정: `/api/tools/stretch-check`, `/api/tools/face-check`
- baseline: `/api/pose/baseline`, `/api/face/baseline`
- 예약: `/api/scheduler/status`, `/api/scheduler/claim`
- 대화: `/api/conversation/start`, `respond`, `timeout`
- 음성: `/api/audio/transcribe`
- 일반 채팅: `/api/chat`
- Agent: `/api/agent/evaluate`

`main.py`의 측정 endpoint는 계산만 하지 않는다. 성공 시 baseline과 비교하고 일별 history에도 저장한다.

### `backend/app/pose_tool.py` — 자세 품질 검사와 특징 계산

발표용 한 문장:

> 브라우저가 보낸 관절 좌표가 믿을 만한지 먼저 검사한 뒤, 양팔 각도와 높이 차이를 계산합니다.

처리 순서:

1. 자세가 검출되었는지 확인한다.
2. 8개 중 최소 3개, 전체의 60% 이상 검출되었는지 확인한다.
3. 33개 landmark와 어깨·팔꿈치·손목 visibility를 확인한다.
4. 팔이 화면 밖으로 나갔는지 확인한다.
5. 카메라 영상의 가로세로 비율을 반영해 팔꿈치 각도를 계산한다.
6. 좌우 팔 각도·높이·손목 높이 차이를 반환한다.

성공 결과는 `success`, `quality`, `features`, `change_from_baseline`, `error`의 일정한 형식을 사용한다.

### `backend/app/face_tool.py` — 얼굴 품질 검사와 비대칭 특징 계산

발표용 한 문장:

> 얼굴이 충분히 크고 정면이며 안정적인지 검증한 뒤, 고개 기울기를 보정하고 입꼬리와 코 중심의 좌우 차이를 계산합니다.

처리 순서:

1. 얼굴 검출률과 landmark 개수를 확인한다.
2. 브라우저가 계산한 안정성 점수를 검사한다.
3. 얼굴이 프레임 밖인지, 너무 작은지 확인한다.
4. 양 눈 기울기로 head roll을 계산하고 25도 초과 시 재측정을 요청한다.
5. 양 볼과 코 위치로 정면 여부를 추정한다.
6. 기울기를 보정한 좌표에서 `mouth_tilt`, `nose_center_offset`, `mouth_eye_distance`를 계산한다.

현재 HTTP 흐름에서는 `main.py`가 저장된 얼굴 baseline으로 `change_from_baseline`을 다시 계산한다. 요청 모델의 `baseline_features` 필드는 단독 함수 테스트와 다른 client를 위해 남아 있지만 현재 React 화면은 보내지 않는다.

### `backend/app/pose_store.py` — 개인 기준과 이력 저장소

발표용 한 문장:

> 자세와 얼굴의 개인 baseline을 만들고, 현재 측정이 평소 범위를 벗어났는지 계산하며, 결과를 날짜별 JSON으로 저장합니다.

핵심 규칙:

- baseline 준비에 최소 3개 샘플이 필요하다.
- 최대 20개 샘플을 유지한다.
- baseline에 넣을 측정 품질은 0.65 이상이어야 한다.
- 평균, 표준편차, 최솟값, 최댓값을 feature별로 저장한다.
- 변화 허용치는 `max(고정 최소값, 표준편차 × 3)`이다.
- 저장 시 임시 파일을 만든 후 `replace`해 중간 상태 파일이 남을 가능성을 줄인다.

`PoseDataStore`라는 이름이지만 자세뿐 아니라 얼굴 baseline과 얼굴 측정 history도 관리한다.

### `backend/app/scheduler.py` — 정시 이벤트 관리자

발표용 한 문장:

> 서버의 로컬 시간을 기준으로 정해진 시각의 건강 확인 이벤트를 한 번만 발행합니다.

핵심 규칙:

- 예약 시각: 08, 10, 12, 14, 16, 18, 20시
- 정시부터 15분 안에만 이벤트를 claim할 수 있다.
- 08시는 `morning`, 나머지는 `periodic` 순서다.
- 마지막 claim 슬롯을 JSON으로 저장해 서버 재시작 후 중복 실행을 막는다.
- `threading.Lock`으로 한 프로세스 안의 동시 claim을 막는다.

주의할 점:

- `.env`의 `CHECK_INTERVAL_SECONDS`는 현재 이 파일에서 사용하지 않는다.
- `start_after_morning()`이라는 이름과 달리 현재는 단순히 상태만 반환한다.
- timezone을 코드에 서울로 고정하지 않고 서버의 `astimezone()`을 사용한다.

### `backend/app/conversation.py` — 상태를 가진 건강 대화

발표용 한 문장:

> 이벤트별 대화를 만들고, 최근 대화 문맥과 사용자 응답을 저장하며, 후속 질문·종료·추가 측정 여부를 결정합니다.

구성 요소:

- Pydantic request/response 모델: API 계약
- `GeminiConversationGenerator`: Gemini 구조화 응답으로 질문 생성
- `LocalConversationGenerator`: API 키가 없을 때 고정 질문과 길이 기반 처리
- `ConversationStore`: 날짜별 대화 JSON과 event index 저장
- `ConversationService`: 안전 규칙과 생성 결과를 합쳐 최종 동작 결정

핵심 동작:

- 같은 event ID로 시작하면 새 대화를 만들지 않고 기존 대화를 반환한다.
- 최근 다섯 대화를 보고 같은 시작 질문 반복을 줄인다.
- 첫 응답 뒤에는 일반적으로 “더 들려주실 말씀”을 묻는 후속 질문을 제공한다.
- 사용자가 “더 할 말 없어요”라고 하거나 후속 녹음이 무음이면 종료한다.
- 문맥에 맞지 않는 응답이 두 번 누적되면 `needs_additional_checks`를 켠다.
- 음성 transcript는 전사 직후가 아니라 대화 응답으로 실제 채택될 때 저장한다.

### `backend/app/stroke_screening.py` — 고정된 안전 규칙

발표용 한 문장:

> 생성형 AI와 별개로, 측정 변화와 사용자의 명시적 증상 표현을 규칙으로 확인해 긴급 안내 여부를 결정합니다.

측정에서 보는 feature:

- 자세: 팔 각도 좌우 차이, 손목 높이 좌우 차이
- 얼굴: 입꼬리 기울기

문장에서 찾는 증상:

- 한쪽 얼굴 처짐
- 한쪽 팔·다리 힘 빠짐
- 말하기·이해하기 어려움
- 갑작스러운 균형 또는 시야 이상
- 원인 불명의 갑작스러운 심한 두통

부정 표현, 긍정 표현, 불명확한 표현을 나누어 처리한다. 측정 수치만으로 긴급 상태를 확정하지 않고 반드시 사용자의 증상 확인을 거친다는 점이 핵심이다. 단, 사용자가 측정 신호 없이도 갑작스러운 명시적 증상을 말하면 긴급 안내가 가능하다.

### `backend/app/audio_tool.py` — 음성 전사 계층

발표용 한 문장:

> 업로드된 오디오를 검증하고 local whisper.cpp 또는 OpenAI Whisper 중 설정된 backend로 한국어 transcript를 만듭니다.

주요 class:

- `OpenAIWhisperTranscriber`: OpenAI Audio API 호출
- `LocalWhisperCppTranscriber`: ffmpeg와 로컬 `whisper-cli` 실행
- `AudioTranscriptionService`: backend 선택, 공통 검증, 오류 형식 통일

검증 내용:

- 허용 형식인지 확인
- 10MB 이하인지 확인
- 0.8~60초 범위인지 확인
- 빈 파일인지 확인
- `(음악)`, `[침묵]` 같은 noise marker 제거
- 빈 transcript를 silence 오류로 반환

local 방식은 임시 디렉터리에만 원본과 변환 WAV를 만들며 작업이 끝나면 삭제한다.

### `backend/app/agent.py` — Tool 결과 평가 Agent

발표용 한 문장:

> 측정 Tool 결과를 Gemini function calling 또는 동일 계약의 규칙 기반 fallback으로 평가해 종료, 재시도, 질문, 추가 Tool 요청 중 하나를 반환합니다.

가능한 action:

- `finish`: 확인 종료
- `retry`: 현재 측정 재시도
- `ask_user`: 사용자에게 추가 질문
- `request_tool`: 다른 측정 Tool 요청

Gemini는 `get_history`를 호출해 최근 측정 기록을 볼 수도 있다. 무한 반복 방지를 위해 기본 최대 네 번의 Tool 선택만 허용한다.

가장 중요한 현재 상태:

> 이 API는 구현되고 테스트되지만 현재 React UI 루틴에서는 호출하지 않는다. 실제 화면은 `App.jsx`가 다음 Tool을 직접 결정한다.

따라서 “중앙 Agent가 전체 루틴을 완전히 지휘하는가?”라는 질문에는 “백엔드 구조는 준비되어 있지만 현재 UI 통합은 일부만 완료되었다”고 답하는 것이 정확하다.

### `backend/app/chat.py` — 일반 대화

루틴 밖에서 사용자가 입력한 메시지에 답한다. Gemini가 있으면 최근 10개 화면 메시지를 함께 보내 구조화 응답을 받고, 키가 없으면 고정 fallback 문장을 반환한다. 의료 수치를 추측하거나 질병을 확정하지 않도록 별도 system prompt를 사용한다.

### `backend/app/prompts.py` — Agent prompt 조립

프로젝트 루트의 `prompt.txt`를 읽고, 실제 등록 Tool과 현재 권한 제한을 뒤에 추가한다. `prompt.txt`에 아직 `voice_check` 같은 과거 설계가 남아 있어도 `IMPLEMENTATION_CONTEXT`가 현재 구현에는 별도 voice Tool이 없음을 명시한다.

`AGENT_PROMPT`는 `agent.py` import 때 만들어지므로 prompt 수정 후에는 백엔드를 재시작하는 것이 안전하다.

### `backend/app/storage.py` — 초기 샘플 저장 API

`backend/data/items.json`의 배열을 읽고 전체 교체하는 단순 저장소다. `/api/items`와 연결되어 있지만 현재 건강 확인 핵심 루틴에서는 사용하지 않는다. 프로젝트 초기 FastAPI 예제의 흔적으로 볼 수 있다.

### `backend/app/__init__.py`

`backend/app`을 Python package로 인식시키는 빈 파일이다. 업무 로직은 없다.

### `backend/requirements.txt`

FastAPI, Uvicorn, Google GenAI, OpenAI, multipart 업로드 라이브러리의 허용 버전 범위를 정의한다.

## 6. 테스트 파일

발표용 한 문장:

> 백엔드는 외부 카메라나 실제 API 없이도 계산과 분기를 검증할 수 있도록 71개의 자동 테스트를 갖고 있습니다.

| 파일 | 검증 내용 |
|---|---|
| `test_pose_tool.py` | 정상 자세, 미검출, 가림, 흔들림, 화면 밖, 카메라 종횡비 |
| `test_face_tool.py` | 정상 얼굴, 안정성, visibility, 얼굴 회전·기울기 보정, baseline 차이 |
| `test_pose_store.py` | baseline 3개 생성, 정상 범위/큰 변화, 날짜별 이력 저장 |
| `test_scheduler.py` | 고정 시간, 오전/주기 순서, 한 번만 claim, 재시작 중복 방지 |
| `test_conversation.py` | 질문 생성, event 재사용, 후속 질문, timeout, transcript, 문맥 이상 |
| `test_stroke_screening.py` | FAST 증상 긍정·부정·불명확 표현과 오탐 방지 |
| `test_audio_tool.py` | 정상·짧은·무음·미지원 음성, noise marker, local Whisper 실행 계약 |
| `test_agent.py` | 종료, 재시도, 추가 Tool, 사용자 질문, history Tool loop |
| `test_integrated.py` | 정상 아침 Pose, Pose 변화, 주기 대화, Face 결과의 모듈 간 연결 |

테스트 실행:

```bash
.venv/bin/python -m unittest discover -s backend/tests -v
cd frontend && npm run build
```

프론트엔드에는 별도 unit test가 없다. 카메라, 마이크, 브라우저 권한, 실제 Gemini/Whisper는 장치 기반 수동 테스트가 필요하다.

## 7. 데이터 파일

### `backend/data/baseline/pose_baseline.json`

자세 baseline의 원본 샘플과 feature별 평균·표준편차·최솟값·최댓값을 저장한다.

### `backend/data/baseline/face_baseline.json`

얼굴 baseline 샘플과 요약 통계를 저장한다.

### `backend/data/history/YYYY-MM-DD.json`

날짜별로 성공한 자세·얼굴 측정 결과와 시각을 누적한다.

### `backend/data/conversations/index.json`

Scheduler event ID를 실제 대화 JSON 경로와 연결한다. 같은 이벤트의 대화를 중복 생성하지 않는 데 사용한다.

### `backend/data/conversations/YYYY-MM-DD/<id>.json`

질문, 사용자 응답, 대화 turn, provider, transcript, 측정 문맥, 긴급 여부 등을 저장한다. 원본 음성은 저장하지 않는다.

### `backend/data/scheduler/state.json`

마지막으로 claim한 예약 시각과 event ID를 저장한다. 서버 재시작 후 같은 슬롯을 다시 실행하지 않게 한다.

### `backend/data/items.json`

초기 샘플 `/api/items`용 데이터다. 건강 측정 핵심 데이터는 아니다.

데이터 파일은 실행 중 변경되므로 발표 자료용 코드와 사용자 데이터로 구분해야 한다. 여러 Uvicorn worker가 동시에 같은 JSON을 쓰는 운영 구조에는 적합하지 않다.

## 8. 루트 설정과 실행 파일

### `start.sh`

발표용 한 문장:

> 환경 변수를 읽고 FastAPI와 Vite를 동시에 시작하며, 한쪽이 종료되거나 Ctrl+C가 입력되면 두 프로세스를 함께 정리하는 실행 스크립트입니다.

추가로 8000/5173 포트 충돌, 가상환경, npm 설치 여부를 미리 검사한다.

### `.env.example`

필요한 환경 변수의 견본이다. Gemini, OpenAI, local Whisper, APP 관련 값을 안내한다. 실제 비밀 키를 넣는 파일이 아니다.

### `.env`, `.env.local`

- `.env`: 실제 API 키와 공통 실행 설정
- `.env.local`: 장치나 개발 환경별 덮어쓰기 설정

`start.sh`가 `.env`를 먼저, `.env.local`을 나중에 읽으므로 같은 변수는 `.env.local` 값이 최종 적용된다. 두 파일은 Git에 포함하면 안 된다.

### `.gitignore`

비밀 환경 파일, 가상환경, 로컬 Whisper, npm 패키지, build 결과, Python cache를 Git 추적에서 제외한다.

### `scripts/setup_local_whisper.sh`

가상환경에 CMake가 없으면 설치하고, `whisper.cpp`를 clone·build한 뒤 `small-q5_1` 모델을 내려받는다. 결과는 `.local/whisper.cpp`에 설치된다. 네트워크, C++ build 환경, ffmpeg가 필요하다.

### `.venv/`, `.local/whisper.cpp/`

- `.venv/`: Python 가상환경과 설치 package
- `.local/whisper.cpp/`: 외부 오픈소스와 build 결과, 모델

둘 다 생성물 또는 외부 코드이므로 우리 프로젝트의 파일별 발표 대상에서는 제외해도 된다.

## 9. 문서와 설계 파일

### `README.md`

프로젝트 소개와 실행 방법을 제공하는 첫 안내 문서다. 다만 `PROGRAM_GUIDE.md`의 위치와 `CHECK_INTERVAL_SECONDS` 설명 등 일부가 현재 구조·코드와 다르므로 현재 동작 설명에는 `my endeavor/DEVELOPER_GUIDE.md`가 더 정확하다.

### `prompt.txt`

Gemini Agent가 지켜야 할 목표, Tool 사용 원칙, 안전 원칙을 담은 사용자 편집 prompt다. 일부 내용은 과거 설계의 `voice_check` 등을 포함하므로 실제 Tool 권한은 `prompts.py`가 덧붙이는 구현 제한과 코드 선언이 최종 기준이다.

### `safty pattern`

안전 패턴에 관한 설계 메모다. 파일명에 `safety`가 아닌 `safty` 오타가 있다. 코드에서 직접 읽지는 않으며 현재 실제 안전 동작은 `stroke_screening.py`와 `conversation.py`에 구현되어 있다.

### `my endeavor/DEVELOPER_GUIDE.md`

현재 코드 기준 구조, 실행, API, 저장 방식, 유지보수 주의사항을 자세히 기록한 개발자 문서다.

### `my endeavor/PROGRAM_GUIDE.md`

이전 단계의 프로그램 안내다. Agent 연결과 Scheduler 설명 중 현재 코드와 다른 부분이 있어 참고 자료로만 사용하는 것이 좋다.

### `my endeavor/CODEX_CLI_IMPLEMENTATION_SPEC.md`

초기 구현 요구사항과 개발 절차를 정의한 명세다. “어떤 목표로 만들기 시작했는가”를 설명할 때 사용한다.

### `my endeavor/CODEX_CLI_IMPLEMENTATION_SPEC_V2.md`

Scheduler, 대화, Whisper, voice baseline, 안전 패턴 등을 더 구체화한 확장 명세다. 모든 항목이 현재 완료되었다는 뜻은 아니며, 구현 여부는 실제 소스 코드로 판단해야 한다.

### `my endeavor/INTEGRATED_SCENARIOS.md`

대표적인 모듈 간 통합 시나리오의 기대 결과와 테스트 통과 기록이다.

### `my endeavor/problem`

측정 실패 UI, 측정 단계 안내, Gemini 채팅 등 당시 해결하려던 짧은 문제 목록이다. 실행에는 사용되지 않는다.

## 10. 파일 연결 관계를 묻는 질문에 답하는 법

### “자세 측정 한 번이 어떤 파일들을 지나가나요?”

```text
App.jsx
 → poseLandmarker.js에서 8프레임 landmark 평균
 → POST /api/tools/stretch-check
 → main.py
 → pose_tool.py에서 품질·특징 계산
 → pose_store.py에서 baseline 비교·history 저장
 → App.jsx가 결과를 보고 종료 또는 Face 단계 선택
```

### “음성 답변은 어떤 파일들을 지나가나요?”

```text
App.jsx의 MediaRecorder
 → POST /api/audio/transcribe
 → main.py
 → audio_tool.py의 local/OpenAI Whisper
 → transcript를 App.jsx가 수신
 → POST /api/conversation/respond
 → conversation.py
 → stroke_screening.py 안전 규칙
 → 대화 JSON 저장
```

### “얼굴 변화가 긴급 경고가 되는 과정은?”

```text
faceLandmarker.js
 → face_tool.py에서 mouth_tilt 계산
 → pose_store.py에서 개인 baseline과 비교
 → conversation.py가 고정 확인 질문 생성
 → stroke_screening.py가 사용자 답변 검사
 → 명시적 증상 확인 시 urgent_alert
 → App.jsx가 119 안내 overlay 표시
```

### “Gemini는 어디에 사용되나요?”

- `agent.py`: Tool 결과 평가 API. 단, 현재 UI 미연결
- `conversation.py`: 일상 질문 생성과 답변 문맥 분석
- `chat.py`: 루틴 외 일반 채팅

Gemini가 없어도 local fallback으로 화면과 측정 흐름을 시험할 수 있다.

## 11. 예상 질의응답

### Q. 왜 영상 전체를 서버로 보내지 않나요?

개인정보 노출과 네트워크 부하를 줄이기 위해 브라우저에서 MediaPipe 추론을 수행한다. 서버에는 평균 landmark 좌표만 전달한다. 다만 landmark도 민감 정보가 될 수 있으므로 운영 단계에서는 전송 암호화와 보관 정책이 추가로 필요하다.

### Q. 최초 사용자의 baseline은 어떻게 등록하나요?

앱이 시작되면 자세와 얼굴 baseline을 조회한다. 하나라도 3개 미만이면 `최초 개인 기준 등록` 카드를 표시하며, 사용자가 시작 버튼을 누르면 자세 3회 후 얼굴 3회 순서로 실제 카메라 측정을 수행한다. 일부 샘플이 이미 있으면 남은 횟수만 진행하고, 실패하면 중단한 뒤 계속 버튼으로 재개할 수 있다.

### Q. 왜 개인 baseline을 사용하나요?

사람마다 자세와 얼굴 형태가 다르므로 하나의 절대 수치보다 자신의 평소값에서 얼마나 변했는지를 보는 편이 프로젝트 목적에 맞기 때문이다. 현재 최소 3개 샘플은 프로토타입 규칙이며 임상적으로 검증된 숫자는 아니다.

### Q. 이 시스템이 뇌졸중을 진단하나요?

아니다. 좌우 비대칭을 보조 신호로 사용하고 사용자에게 FAST 관련 증상을 확인한 뒤 119 연락을 권고할 뿐이다. 확정 진단은 의료진의 영역이다.

### Q. AI가 잘못 판단해서 긴급 경고를 만들 수 있지 않나요?

그래서 긴급 분기의 최종 조건을 Gemini prompt에만 맡기지 않고 `stroke_screening.py`의 고정 규칙으로 제한했다. 측정 변화만으로 경고하지 않고 사용자의 명시적 증상 확인을 결합한다. 그래도 오탐·미탐 가능성은 있어 의료기기로 사용하려면 별도 검증이 필요하다.

### Q. Gemini API가 끊기면 프로그램 전체가 멈추나요?

아니다. 대화와 Agent에 local fallback이 있다. 다만 일반 채팅 답변은 단순해지고, 질문 다양성과 문맥 분석 품질은 낮아진다. 음성은 선택한 Whisper backend가 별도로 준비되어야 한다.

### Q. OpenAI API가 반드시 필요한가요?

아니다. `WHISPER_BACKEND=local`이면 whisper.cpp를 서버에서 실행한다. OpenAI 방식은 `WHISPER_BACKEND=openai`일 때만 필요하다.

### Q. 녹음 파일은 저장되나요?

영구 저장하지 않는다. local 방식은 임시 디렉터리에서 변환·전사 후 삭제하고, 대화 기록에는 채택된 transcript와 duration만 남긴다. OpenAI backend를 사용하면 오디오가 전사를 위해 OpenAI API로 전송된다는 점은 별도로 고지해야 한다.

### Q. Scheduler는 앱이 꺼져 있어도 알림을 보내나요?

아니다. 별도 OS 알림이나 background service가 아니라 실행 중인 브라우저가 15초마다 서버 상태를 확인하는 구조다. 정시 후 15분 안에 서버와 화면이 실행되어 있어야 claim된다.

### Q. 왜 DB 대신 JSON을 사용했나요?

프로토타입을 빠르게 만들고 저장 내용을 직접 확인하기 쉽기 때문이다. 원자적 파일 교체와 process 내부 lock은 있지만, 다중 worker·다중 사용자·대량 데이터 운영에는 DB로 전환해야 한다.

### Q. 여러 사용자가 동시에 사용할 수 있나요?

현재 구조는 사용자 계정이나 tenant 분리가 없고 baseline도 공용 파일 하나를 사용한다. 사실상 한 장치·한 사용자·단일 백엔드 프로세스용 프로토타입이다.

### Q. 중앙 Agent가 모든 Tool을 자율 선택하나요?

백엔드의 `agent.py`에는 그 구조가 구현되어 있지만 현재 React 루틴은 연결되지 않았다. 실제 화면에서는 `App.jsx`가 Pose의 `significant_change`를 보고 Face 실행 여부를 정한다. 완전한 중앙 Agent 구조로 가려면 프론트가 `/api/agent/evaluate` 결과를 따라 상태를 전환하도록 통합해야 한다.

### Q. `CHECK_INTERVAL_SECONDS`를 바꾸면 알림 주기가 바뀌나요?

현재는 바뀌지 않는다. Scheduler는 08시부터 20시까지 두 시간 간격의 고정 슬롯을 코드에 사용한다. 해당 환경 변수는 이전 구현의 흔적이다.

### Q. 테스트가 충분한가요?

백엔드 계산과 분기는 71개 자동 테스트로 검증한다. 그러나 프론트 unit/E2E 테스트, 실제 카메라·마이크, 다양한 조명·자세·브라우저, 실제 외부 API 장애에 대한 현장 검증은 추가로 필요하다.

### Q. 가장 먼저 개선할 부분은 무엇인가요?

1. `App.jsx`를 화면, 장치, 루틴 상태 머신으로 분리한다.
2. 프론트를 Agent API와 연결해 분기 책임을 한곳으로 모은다.
3. 사용자별 인증과 DB 저장을 도입한다.
4. HTTPS, 민감 데이터 보관 정책, 감사 로그를 마련한다.
5. 프론트 unit/E2E 및 실제 장치 테스트를 추가한다.
6. baseline 기준과 위험 threshold를 전문가 데이터로 검증한다.

## 12. 발표 마무리 문장

> 이 프로젝트의 핵심은 카메라·음성·대화를 무조건 AI에 맡기는 것이 아니라, 브라우저 추론, 개인 baseline, 구조화된 API, 고정 안전 규칙을 단계적으로 결합한 데 있습니다. 현재는 단일 사용자용 프로토타입이며, 운영 단계로 가기 위해서는 Agent 통합, DB와 인증, 임상적 기준 검증, 실제 장치 테스트가 다음 과제입니다.
