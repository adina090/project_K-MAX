# Stroke Early-Sign AI Agent - Codex CLI Implementation Spec

> 이 문서는 Codex CLI가 프로젝트의 목적과 구조를 오해하지 않고
> 단계적으로 구현하도록 하기 위한 개발 명세이다.

## 0. 최우선 원칙

-   이 프로그램은 뇌졸중을 진단하거나 확진하는 의료기기가 아니다.
-   목적은 사용자의 평상시 상태와 비교하여 관련 이상 징후의 변화를
    확인하고 추가 확인/도움 요청을 지원하는 것이다.
-   단일 센서 결과만으로 뇌졸중 여부를 확정하지 않는다.
-   측정 실패와 이상 징후를 반드시 구분한다.
-   약 구매 기능을 자동 실행하지 않는다.
-   기능을 한꺼번에 구현하지 않는다.
-   각 PROCEDURE가 끝나면 멈추고 사용자의 Raspberry Pi 실제 테스트
    결과를 기다린다.
-   사용자가 다음 단계 진행을 명시적으로 승인하기 전에는 다음
    PROCEDURE를 구현하지 않는다.
-   기존 동작 코드를 수정할 때는 먼저 관련 파일을 읽고 영향 범위를
    설명한다.
-   불필요한 대규모 리팩터링, 새 프레임워크 도입, 의존성 추가를 피한다.

## 0.5 추가 구현 원칙

다음 사항은 현재 프로젝트의 기본 개발 방향으로 적용한다.

1. **Gemini API를 중앙 AI Agent로 사용한다.**
   - Gemini API를 프로젝트의 기본 중앙 AI로 둔다.
   - Gemini는 각 분석 Tool의 결과를 입력받고, 현재 상황에서 어떤 Tool을 사용할지 판단한다.
   - 실제 센서 계산, MediaPipe 분석, 음향 특징 추출 등은 개별 Tool이 담당한다.
   - Gemini는 Tool 결과를 바탕으로 다음 행동을 선택하는 orchestration 역할을 맡는다.

2. **프론트엔드는 기존에 준비된 파일을 우선 사용한다.**
   - 새로운 UI를 처음부터 다시 만들지 않는다.
   - 프로젝트에 이미 존재하는 프론트엔드 파일을 먼저 분석한 뒤 해당 구조를 유지하면서 기능을 연결한다.
   - 필요한 경우에만 최소한의 UI 수정 및 컴포넌트 추가를 수행한다.

3. **안전 패턴은 후속 단계에서 별도로 설정할 수 있도록 구조만 분리한다.**
   - 초기 구현에서는 핵심 Agent 흐름과 Tool 호출 구조를 우선 완성한다.
   - 안전 관련 규칙은 코드 내부에 하드코딩하지 말고 이후 쉽게 추가/수정할 수 있도록 별도의 설정 또는 모듈로 분리 가능한 구조를 유지한다.
   - 단, 현재 문서의 기본 의료 안전 원칙은 계속 준수한다.

4. **Tool 선택은 AI Agent가 자율적으로 판단한다.**
   - 고정된 순서로 모든 Tool을 실행하지 않는다.
   - Gemini가 현재 측정 결과, baseline, history, quality, user context를 바탕으로 필요한 Tool을 선택한다.
   - Tool 호출 결과는 다시 Gemini에게 전달하고, Gemini가 다음 행동을 재판단한다.
   - 단, 허용된 Tool 목록 밖의 행동은 수행하지 않는다.

5. **포즈 오버랩 가이드 이미지를 제공한다.**
   - 사용자가 현재 자세를 평소 자세와 쉽게 비교할 수 있도록 오버랩 이미지를 표시한다.
   - baseline/history 중 가장 최근의 유효한 포즈 이미지를 기준 이미지로 사용한다.
   - 가장 최근 포즈 이미지는 현재 카메라 화면 위에 약간 투명하게 겹쳐 표시한다.
   - 목적은 사용자가 팔과 몸의 위치를 이전 정상 자세에 맞추기 쉽게 하는 것이다.
   - 이미지 저장/표시 시 개인정보 및 로컬 저장 범위를 고려하고, 필요 시 이미지 대신 landmark skeleton 오버레이로 대체 가능하도록 한다.

6. **UI 및 개발 기준 화면은 세로 화면이다.**
   - 데스크톱 가로 화면을 기본 기준으로 설계하지 않는다.
   - Raspberry Pi에 연결될 실제 세로형 디스플레이 또는 세로 브라우저 화면을 기준으로 프론트엔드를 구성한다.
   - 레이아웃, 카메라 영역, Agent 대화 영역, 상태 정보는 세로 화면에서 읽기 쉽게 배치한다.
   - 반응형 처리는 가능하지만 우선순위는 portrait layout이다.

## 1. Project Goal

고령 사용자의 상태를 **아침 스트레칭 + 주기적인 대화**를 통해 확인한다.

기본 운영 방식:

```text
[아침]
Morning routine
-> stretch_check
-> pose baseline/history comparison
-> Gemini Agent decision
-> 필요 시 추가 Tool 선택

[이후 약 4시간 간격]
Scheduler
-> Gemini가 먼저 사용자에게 대화 시작
-> 사용자 음성 녹음
-> OpenAI Whisper로 음성 인식(STT)
-> 음성 특징 + 인식 결과 + 대화 맥락 정리
-> Gemini가 개인 baseline/history와 비교
-> 필요한 추가 Tool 또는 재측정 여부 판단
```

프로젝트의 핵심 목적은 뇌졸중을 진단하는 것이 아니라, 사용자의 평상시 상태를 기억하고 일상적인 대화와 동작에서 **평소와 다른 변화가 나타나는지 주기적으로 확인**하는 것이다.

Gemini API 기반 AI Agent는 중앙 controller/orchestrator 역할을 담당한다. 실제 Pose 측정, 음성 녹음, Whisper STT, 음향 특징 추출 등은 Tool이 수행하고, Gemini는 그 결과와 맥락을 바탕으로 다음 행동과 사용할 Tool을 자율적으로 선택한다.


## 2. Agent Definition

### Input

Agent가 받을 수 있는 정보:

``` json
{
  "check_type": "morning_stretch | periodic_conversation",
  "pose_result": {},
  "face_result": {},
  "voice_result": {},
  "whisper_transcript": "",
  "conversation_context": [],
  "baseline": {},
  "recent_history": [],
  "measurement_quality": {},
  "user_context": {}
}
```

모든 값이 항상 존재한다고 가정하지 말 것.

### Judgment

Agent가 판단할 내용:

1.  현재 측정 데이터가 사용 가능한가?
2.  개인 baseline과 비교하여 유의미한 변화가 있는가?
3.  현재 정보만으로 충분한가?
4.  어떤 추가 Tool이 필요한가?
5.  재측정이 필요한가?
6.  검사를 종료할 수 있는가?
7.  안전한 후속 행동이 필요한가?

### Action

Agent가 허용된 Tool 중 하나 또는 필요한 최소 개수를 선택한다.

### Output

Agent 결과는 UI에 사람이 이해할 수 있는 형태로 표시한다.

예:

``` json
{
  "status": "additional_check",
  "reason": "Arm movement differs from personal baseline.",
  "next_tool": "face_check",
  "user_message": "팔 움직임에 평소와 다른 변화가 있어 추가 확인을 진행합니다."
}
```

내부 reasoning/chain-of-thought를 UI나 로그에 출력하지 말 것. 대신 짧은
`reason`만 기록한다.

## 3. Tool Interface

우선 다음 인터페이스를 기준으로 설계한다.

```python
# Morning / vision
stretch_check() -> PoseResult
face_check() -> FaceResult

# Periodic voice conversation
start_conversation() -> ConversationPrompt
record_voice() -> AudioResult
whisper_transcribe(audio_path: str) -> TranscriptResult
extract_voice_features(audio_path: str) -> VoiceFeatureResult
analyze_conversation_context(transcript: str, history) -> ContextResult
voice_check() -> VoiceResult

# Data
get_baseline(data_type: str) -> BaselineResult
get_history(data_type: str, days: int) -> HistoryResult
save_measurement(result) -> SaveResult

# Agent actions
retry_measurement(tool_name: str, reason: str) -> RetryResult
ask_user(question: str) -> UserResponse
contact_guardian(message: str) -> ActionResult
finish_check(message: str) -> ActionResult
```

### Voice Tool 내부 권장 흐름

```text
Gemini starts conversation
-> record_voice()
-> whisper_transcribe()
-> extract_voice_features()
-> analyze_conversation_context()
-> merge results
-> return structured VoiceResult to Gemini
```

OpenAI Whisper는 **음성 인식(STT)** 용도로 사용한다.

Whisper 전사 결과만으로 발음 어눌함이나 뇌졸중 여부를 확정하지 않는다. 가능한 경우 음향 특징(발화 시간, 무음 비율, 발화 속도 등)과 개인의 기존 기록을 함께 사용하여 **평소와의 변화 여부**를 계산한다.

실제 함수명이 기존 코드와 다르면 기존 구조를 우선하고 문서만 일치하도록 업데이트한다.


## 4. Measurement Result Contract

모든 측정 Tool은 가능한 한 공통 필드를 가진다.

``` json
{
  "success": true,
  "quality": 0.92,
  "features": {},
  "change_from_baseline": {},
  "error": null
}
```

### 중요

`success == false` 또는 quality가 기준 이하라면 이상 징후로 판단하지
않는다.

다음 행동 후보:

``` text
measurement failure
-> explain problem briefly
-> guide user
-> retry_measurement()
```

반복 실패 시 무한 루프를 만들지 말고 예외 종료 상태를 반환한다.

## 5. Data Structure

권장:

```text
data/
├── baseline/
│   ├── pose_baseline.json
│   ├── face_baseline.json
│   └── voice_baseline.json
├── history/
│   └── YYYY-MM-DD.json
├── conversations/
│   └── YYYY-MM-DD/
│       ├── HH-MM_transcript.json
│       └── HH-MM_voice_features.json
└── pose_images/
    └── latest_pose.jpg
```

### pose baseline

가능한 특징:
- left_arm_angle
- right_arm_angle
- arm_angle_difference
- left_arm_height
- right_arm_height
- measurement_quality

### face baseline

가능한 특징:
- landmark-derived asymmetry values
- mouth asymmetry
- other implemented facial asymmetry values
- measurement_quality

### voice baseline

구현 가능한 범위에서:
- speech_rate
- silence_ratio
- duration
- pause_count 또는 평균 pause length
- MFCC summary (필요 시)
- Whisper transcript 관련 메타데이터
- measurement_quality

### conversation history

주기적인 대화마다 다음 정보를 가능한 범위에서 저장한다.

```json
{
  "timestamp": "YYYY-MM-DDTHH:MM:SS",
  "agent_question": "...",
  "transcript": "...",
  "voice_features": {},
  "comparison_to_baseline": {},
  "context_summary": "",
  "next_action": ""
}
```

개인정보가 포함될 수 있으므로 원본 오디오는 기본적으로 장기 저장하지 않고, 필요한 경우 사용자 설정에 따라 보관 여부를 결정할 수 있도록 한다.


## 6. Core Decision Principle

프로그램은 두 가지 주요 확인 루틴을 가진다.

### A. Morning Stretch Check

```text
아침 시작
-> stretch_check()
-> pose baseline/history 비교
-> Gemini 판단
-> 필요 시 추가 Tool 선택
```

### B. Periodic Conversation Check

기본 주기는 약 **4시간 간격**으로 설정한다. 주기는 config에서 쉽게 변경할 수 있어야 한다.

```text
scheduled time
-> Gemini가 먼저 자연스러운 질문 생성
-> 사용자 응답 녹음
-> Whisper STT
-> 음향 특징 추출
-> 대화 맥락 정리
-> voice baseline/history 비교
-> Gemini 판단
-> 필요 시 추가 질문 / 재측정 / 다른 Tool 호출
```

### Agent 판단 원칙

고정된 모든 Tool을 항상 실행하지 않는다.

예:

```text
Pose normal + high quality
-> finish morning check

Periodic conversation
+ Whisper transcription success
+ voice features close to baseline
+ context normal
-> save and finish

Voice recording quality low
-> retry voice

Transcript가 비정상적으로 끊기거나
voice features가 baseline과 크게 다르고
대화 맥락도 평소와 다른 경우
-> Gemini가 추가 질문 또는 다른 Tool 선택
```

단순 threshold 계산은 일반 코드가 담당할 수 있다.

Agent의 핵심 역할은 다음을 종합해 다음 행동을 선택하는 것이다.

```text
measurement result
+ measurement quality
+ Whisper transcript
+ voice features
+ conversation context
+ personal baseline
+ recent history
+ available tools
+ user context
```

Gemini가 임의의 의학적 임계값을 만들어내지 않도록 한다. 숫자 기반 변화량과 데이터 품질은 가능한 한 Tool/일반 알고리즘이 계산하고, Gemini는 **추가 확인이 필요한지와 어떤 Tool을 사용할지**를 판단한다.


## 7. Safety Rules

금지: - "뇌졸중입니다"와 같은 확진 출력 - 한 가지 측정만으로 확정적인
의료 판단 - 측정 실패를 이상으로 취급 - 자동 의약품 구매 - Agent가
정의되지 않은 임의의 외부 행동 실행

허용되는 표현 예:

``` text
"평소와 다른 변화가 확인되어 추가 확인을 진행합니다."

"측정 품질이 충분하지 않아 다시 측정하겠습니다."

"여러 관련 이상 징후가 함께 확인되었습니다. 신속하게 주변의 도움을 요청하세요."
```

응급 상황을 다루는 실제 기능은 팀이 정한 안전 절차와 명확한 사용자
동의/설정 범위에서 구현한다.

## 8. UI Requirements

프론트엔드는 프로젝트에 이미 존재하는 파일을 우선 사용하고, 전체 레이아웃은 세로 화면(portrait)을 기준으로 수정한다.

기본 UI 목표:

``` text
+----------------------+----------------------+
| Agent conversation   | Camera / measurement |
|                      |                      |
| Tool selected        | Pose/Face status     |
| Short reason         | Current values       |
| Result               | Baseline comparison  |
+----------------------+----------------------+
```

세로형 화면에서 기본적으로 다음 상태를 표현한다.

- 아침 루틴인지 주기적 대화 루틴인지
- 다음 주기적 확인까지 남은 시간 또는 마지막 확인 시각
- Gemini의 대화 메시지
- Whisper 전사 결과(필요 시)
- 현재 측정/비교 상태

Agent 영역에서 보여줄 것: - 현재 단계 - 호출한 Tool - Tool 결과 요약 -
다음 행동 - 사용자에게 필요한 안내

내부 chain-of-thought는 표시하지 않는다.

### Pose Overlay

- 가장 최근의 유효한 baseline/history 포즈 이미지를 불러온다.
- 현재 카메라 화면 위에 투명도를 적용하여 겹쳐 표시한다.
- 사용자가 이전 자세와 현재 자세를 쉽게 맞출 수 있도록 한다.
- 이미지가 없으면 해당 기능은 비활성화하고 일반 카메라 화면만 표시한다.
- 구현 안정성이 더 높은 경우 실제 이미지를 겹치는 대신 최근 landmark skeleton을 반투명하게 표시할 수 있다.



## 8.5 Periodic Scheduler / Conversation Architecture

약 4시간마다 주기적 대화를 시작할 수 있도록 scheduler를 별도 모듈로 분리한다.

권장 파일:

```text
scheduler/
├── periodic_check.py
└── schedule_config.py
```

권장 동작:

```text
App start
-> scheduler start
-> 다음 periodic check 시간 계산

scheduled event
-> Gemini Agent 호출
-> start_conversation()
-> record_voice()
-> Whisper STT
-> voice/context analysis
-> Gemini next action
-> save history
-> next schedule
```

중요:
- 4시간은 기본값이며 config에서 변경 가능해야 한다.
- 프로그램 재시작 후에도 마지막 실행 시각을 읽어 중복 실행을 피할 수 있도록 한다.
- 테스트 단계에서는 4시간을 실제로 기다리지 않도록 개발용 interval을 별도 설정 가능하게 한다.
- Scheduler가 UI나 Agent loop를 block하지 않도록 구성한다.


## 9. Known Bugs / Issues

### ISSUE-001 Camera

증상: - 카메라 화면이 UI에 표시되지 않음.

조사 순서: 1. camera device open 여부 2. frame read 성공 여부 3. frame
conversion 여부 4. UI rendering 여부

입력 문제와 표시 문제를 분리하여 디버깅할 것.

### ISSUE-002 Voice

기존 STT 중심 음성 기능을 다음 구조로 변경한다.

목표:

```text
microphone recording
-> OpenAI Whisper STT
-> transcript
-> acoustic feature extraction
-> conversation context
-> personal baseline/history comparison
-> Gemini decision
```

필수:
- OpenAI Whisper를 STT engine으로 사용
- 녹음 실패와 전사 실패를 별도로 처리
- Whisper 결과만으로 '어눌함'을 확정하지 않음
- 동일 사용자의 과거 음성과 비교 가능한 특징을 함께 저장
- Gemini가 transcript의 대화 맥락과 구조화된 voice data를 함께 볼 수 있도록 함

구현 시간이 부족하면 최소 기능 우선순위:

1. 녹음
2. Whisper 전사
3. duration / silence ratio
4. baseline 저장 및 비교
5. Gemini context 판단
6. 추가 음향 특징


### ISSUE-003 Pose failure handling

현재 문제: - Pose가 제대로 인식되지 않아도 다음 단계로 진행할 수 있음.

수정 목표:

``` text
landmark/confidence insufficient
-> do NOT continue
-> guide user
-> retry
-> if repeated failure: exception state
```

## 10. Development Procedures

현재 개발 진행 상황:

- **PROCEDURE 1: 완료**
- **PROCEDURE 2: 완료**
- 다음 개발은 **PROCEDURE 3부터 시작한다.**
- 완료된 1~2단계를 임의로 다시 구현하거나 대규모 수정하지 않는다. 현재 코드를 먼저 확인하고 필요한 호환 수정만 한다.

### PROCEDURE 1 - Existing Project Inspection [COMPLETED]

기존 프로젝트 구조, entry point, camera / pose / UI 흐름 확인.

### PROCEDURE 2 - Pose Reliability [COMPLETED]

stretch/pose 핵심 기능, landmark/confidence, 실패 처리 및 retry 기반을 구현한 상태로 간주한다.

---

### PROCEDURE 3 - Personal Pose Baseline + Latest Pose Overlay

목표:
- 개인 pose baseline 저장/로드/비교
- 최근 유효한 포즈 이미지를 현재 카메라에 반투명 overlay

구현:
- 정상 pose 여러 회 저장 가능
- baseline summary
- current vs baseline 변화량
- history 저장
- latest valid pose image 저장
- portrait UI에서 최근 이미지를 투명하게 overlay

테스트:
1. baseline 없음
2. baseline 생성
3. 최근 이미지 overlay
4. 정상 범위 자세
5. 큰 좌우 차이

완료 후 STOP.

### PROCEDURE 4 - Gemini Central Agent

목표:
- Gemini API를 중앙 Agent로 연결한다.

구현:
- tool registry
- Agent prompt
- structured tool results
- Gemini function/tool calling
- tool result -> Gemini -> next action loop

최소 행동:
- finish
- retry
- request history
- ask user
- request pose/face/voice tool

중요:
- Gemini가 측정값을 생성하지 않는다.
- 실제 Tool 결과만 근거로 한다.
- 짧은 reason과 선택 Tool만 UI/log에 표시한다.
- 내부 chain-of-thought는 출력하지 않는다.

테스트:
1. normal pose -> finish
2. changed pose -> additional tool
3. low-quality data -> retry

완료 후 STOP.

### PROCEDURE 5 - Periodic Scheduler

목표:
- 아침 스트레칭 이후 약 4시간마다 대화 확인 루틴을 실행한다.

구현:
- configurable interval
- 기본 production interval: 4 hours
- 개발용 짧은 interval 지원
- last check timestamp 저장
- 중복 호출 방지
- UI/Agent loop non-blocking

테스트:
1. 개발용 1~2분 interval
2. scheduled event 한 번만 실행
3. app restart 후 중복 방지

완료 후 STOP.

### PROCEDURE 6 - Gemini Conversation Initiation

목표:
- 주기적 확인 시간이 되면 Gemini가 먼저 사용자에게 자연스럽게 말을 건다.

예시 목적:
- 사용자가 한두 문장 이상 자연스럽게 말하도록 유도
- 매번 완전히 동일한 질문만 반복하지 않음
- 의료 진단 질문보다는 일상적인 대화를 우선

예시:
- 오늘 점심은 어땠나요?
- 지금 기분은 어떠세요?
- 오늘 있었던 일을 간단히 이야기해 주세요.

구현:
- start_conversation()
- user response recording trigger
- conversation history 전달
- 필요 시 follow-up question

완료 후 STOP.

### PROCEDURE 7 - OpenAI Whisper STT

목표:
- 사용자 음성을 OpenAI Whisper로 전사한다.

구현:
- microphone recording
- audio file/stream handling
- Whisper transcription
- error handling
- TranscriptResult 구조화

권장 반환:

```json
{
  "success": true,
  "transcript": "...",
  "duration": 4.8,
  "error": null
}
```

테스트:
1. 정상 발화
2. 짧은 발화
3. 무음
4. 주변 소음
5. API/네트워크 실패

완료 후 STOP.

### PROCEDURE 8 - Voice Baseline / Speech Change Features

목표:
- Whisper transcript뿐 아니라 음성 자체의 변화량도 구조화한다.

최소 특징:
1. duration
2. silence_ratio
3. speech_rate (구현 가능한 방식)
4. 녹음 품질

시간이 허용되면:
- pause statistics
- MFCC summary

개인 baseline과 현재 값을 비교하여 `change_from_baseline`을 계산한다.

주의:
- 이 score를 뇌졸중 확률로 표현하지 않는다.
- '평소 발화와 비교한 변화 정도'로만 사용한다.

완료 후 STOP.

### PROCEDURE 9 - Conversation Context Analysis

목표:
- Whisper transcript와 대화 기록을 Gemini에게 제공하여 대화가 자연스럽게 이어지는지 맥락을 파악한다.

Gemini 입력:
- 현재 질문
- 현재 transcript
- 최근 대화 일부
- voice feature comparison
- measurement quality

Gemini가 판단 가능한 것:
- 답변이 질문 맥락과 연결되는지
- 추가 질문이 필요한지
- 음성 재측정이 필요한지
- 다른 Tool 확인이 필요한지
- 이번 주기 확인을 종료할지

금지:
- transcript만 보고 의료적 진단 확정
- 의학적 임계값 임의 생성

완료 후 STOP.

### PROCEDURE 10 - Face Tool

목표:
- Gemini가 필요하다고 판단했을 때만 Face Tool을 호출할 수 있도록 연결한다.

구현:
- landmark detection
- implemented asymmetry feature
- quality
- baseline comparison
- failure handling

완료 후 STOP.

### PROCEDURE 11 - Integrated Agent Scenarios

반드시 테스트:

1. 아침 정상 pose
2. 아침 pose 변화 감지
3. 주기적 대화 정상
4. 주기적 대화 녹음 실패
5. Whisper 전사 실패
6. voice data가 평소와 크게 다른 상황
7. Agent가 추가 질문 선택
8. Agent가 다른 Tool 선택

각 테스트마다 기록:

```text
Input
Expected
Actual
Problem
Fix
Retest
```

완료 후 STOP.

### PROCEDURE 12 - Safety Pattern Configuration

핵심 Agent 동작이 안정된 이후 안전 패턴을 별도 설정한다.

목표:
- safety module/config 분리
- 위험한 자동 행동 제한
- 사용자 안내 정책
- 반복 실패 정책
- 보호자 연락 조건 등

완료 후 STOP.

### PROCEDURE 13 - Final Documentation

사용자 승인 후 다음 문서를 생성/갱신한다.

`README.md` 또는 `PROGRAM_GUIDE.md`

포함:
- 프로젝트 목적
- 아침 루틴
- 4시간 주기 대화 루틴
- Gemini Agent architecture
- Whisper architecture
- directory/file roles
- installation
- execution
- Agent flow
- Tool descriptions
- data format
- configuration
- error handling
- test scenarios
- known limitations
- future improvements


## 11. Definition of Done

핵심 데모가 다음 두 경로를 실제로 보여주면 성공:

### Morning Path

```text
real camera input
-> pose measurement
-> personal baseline comparison
-> Gemini Agent decision
-> dynamic Tool/action selection
-> visible result in portrait UI
```

### Periodic Conversation Path

```text
scheduled check
-> Gemini starts conversation
-> user voice recording
-> OpenAI Whisper transcription
-> voice feature extraction
-> baseline/history comparison
-> conversation context
-> Gemini Agent decision
-> follow-up / retry / additional Tool / finish
```

Face Tool이나 고급 음향 분석이 완벽하지 않더라도 **아침 Pose 경로 + 주기적 대화/Whisper 경로 + Gemini의 동적 Tool 선택**이 실제로 안정적으로 동작하는 것을 우선한다.


## 12. Codex CLI Response Style

작업 중 답변은 짧고 명확하게 한다.

각 PROCEDURE 종료 시 다음 형식을 사용한다.

``` text
[PROCEDURE N COMPLETE]

변경 파일:
- ...

구현 내용:
- ...

Raspberry Pi 테스트:
1. ...
2. ...

예상 결과:
- ...

다음 단계:
사용자 테스트 결과를 기다림.
```

테스트 결과를 받기 전에는 다음 PROCEDURE를 시작하지 않는다.
