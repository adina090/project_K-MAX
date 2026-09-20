# 건강 확인 테스트 프로그램 가이드

## 목적

FastAPI 백엔드와 React 프론트엔드로 구성된 건강 확인 프로토타입입니다. JSON 파일을
사용해 자세 측정 이력, 개인 기준, scheduler 상태, 대화 기록을 저장합니다.

현재 데모의 핵심은 다음 두 흐름입니다.

1. 사용자가 버튼을 눌렀을 때 카메라를 열고 자세를 측정합니다.
2. 주기적 scheduler 이벤트가 발생하면 텍스트 대화를 시작하고 Gemini가 후속 질문 또는 종료를 선택합니다.

## 실행

```bash
cp .env.example .env
# .env에 GEMINI_API_KEY를 입력
bash start.sh
```

- React: `http://localhost:5173`
- FastAPI: `http://localhost:8000`
- API 문서: `http://localhost:8000/docs`

수동 실행이 필요하면 README의 백엔드·프론트엔드 실행 명령을 사용합니다.

## 디렉터리

```text
backend/app/
  main.py          API 라우팅
  agent.py         Gemini/로컬 Agent 오케스트레이션
  pose_tool.py     자세 품질·팔 각도 측정
  face_tool.py     얼굴 랜드마크 품질·비대칭 측정
  pose_store.py    자세 baseline·이력 JSON 저장
  scheduler.py     주기적 확인 예약·중복 방지
  conversation.py  텍스트 대화·맥락 저장
  storage.py       공통 JSON 저장소
backend/data/      실행 중 생성되는 JSON 데이터
frontend/src/      React 화면과 Pose Landmarker 연동
```

## Agent 흐름

자세 측정 결과는 `/api/agent/evaluate`로 전달됩니다. Agent는 다음 중 하나를 선택합니다.

- `finish`: 확인 종료
- `retry`: 품질이 부족해 같은 측정 재시도
- `ask_user`: 사용자에게 추가 정보 질문
- `request_tool`: `face_check` 같은 추가 Tool 요청

Gemini 키가 없으면 같은 응답 계약의 로컬 fallback을 사용합니다. Agent는 제공된 Tool
결과만 근거로 판단하며 의료 진단을 확정하지 않습니다.

## 주요 API

- `GET /api/health`
- `POST /api/tools/stretch-check`
- `POST /api/tools/face-check`
- `POST /api/agent/evaluate`
- `GET /api/scheduler/status`
- `POST /api/scheduler/claim`
- `POST /api/conversation/start`
- `POST /api/conversation/respond`
- `POST /api/chat`: 일반 사용자 채팅을 Gemini로 전달
- `GET /api/pose/baseline`
- `POST /api/pose/baseline/samples`

## 데이터 형식

- `backend/data/pose_measurements/`: 자세 측정 이력
- `backend/data/pose_baseline.json`: 개인 기준 샘플과 준비 상태
- `backend/data/scheduler/state.json`: 마지막·다음 scheduler 시각
- `backend/data/conversations/`: 날짜별 대화 JSON

원본 카메라 영상, 얼굴 이미지, 음성 파일은 저장하지 않습니다.

기준 자세는 화면의 실제 카메라 측정이 성공할 때 자동으로 저장됩니다. 최소 3개 샘플이
기준으로 활성화되며, 수동 숫자 입력은 사용하지 않습니다. 기존 기준을 수정할 때는
새로운 실제 측정 샘플을 추가하거나 서버를 중지한 뒤
`backend/data/baseline/pose_baseline.json`을 백업하고 `samples`와 `summary`를 함께
수정합니다.

## 설정

`.env.example`을 기준으로 설정합니다.

- `GEMINI_API_KEY`, `GEMINI_MODEL`: Gemini Agent와 대화 생성
- `CHECK_INTERVAL_SECONDS`: 기본 4시간 주기

Gemini Agent의 시스템 프롬프트는 프로젝트 루트의 `prompt.txt`를 읽어 사용합니다.
프롬프트를 수정한 뒤 서버를 재시작하면 다음 Agent 판단부터 반영됩니다. 실제 등록된
Tool과 외부 연락 권한 제한은 코드가 자동으로 뒤에 추가합니다.

Whisper 음성 인식은 `OPENAI_API_KEY`가 설정된 경우 활성화됩니다. 원본 음성은 저장하지
않고 transcript와 duration만 대화 JSON에 기록합니다. 음성 baseline과 안전 패턴,
보호자 연락 기능은 아직 별도 단계입니다.

## 오류 처리

자세·얼굴 Tool은 `success`, `quality`, `features`, `error` 구조를 반환합니다. 인식 실패,
낮은 가시성, 화면 밖 landmark, 불안정한 샘플은 재시도 가능한 오류로 구분합니다.

Scheduler는 JSON 상태를 원자적으로 저장하고 event ID를 기준으로 중복 대화를 방지합니다.

## 테스트

```bash
./.venv/bin/python -m unittest discover -s backend/tests -v
cd frontend && npm run build
```

현재 백엔드 테스트는 Pose, Face, Agent, Scheduler, 텍스트 Conversation, Whisper 입력
검증 및 통합 시나리오를 검증합니다. 음성 baseline·안전 패턴은 향후 단계입니다.

## 알려진 제한과 다음 작업

- 브라우저 Face Landmarker 호출 UI는 API 계약을 먼저 구현한 상태입니다.
- Whisper STT는 연결되어 있으며 실제 브라우저 발화 테스트가 필요합니다.
- 음성 특징 추출과 baseline 비교는 추후 추가합니다.
- 안전 패턴 설정, 반복 실패 정책, 보호자 연락 조건은 별도 승인 후 추가합니다.
- 실제 카메라·Gemini 키를 사용한 Raspberry Pi 현장 테스트가 필요합니다.
