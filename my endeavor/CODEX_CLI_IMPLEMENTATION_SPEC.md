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

고령자의 아침 루틴에서 팔 움직임, 얼굴, 음성 데이터를 수집하고 개인
baseline/history와 비교한다.

AI Agent는 측정 알고리즘 자체가 아니라 다음 행동을 결정하는
controller/orchestrator 역할을 담당한다.

핵심 흐름:

``` text
Morning routine
-> stretch_check
-> baseline/history comparison
-> Agent decision
   -> finish
   -> request retry
   -> face_check
   -> voice_check
   -> get_history
   -> ask_user
   -> safe follow-up action
```

## 2. Agent Definition

### Input

Agent가 받을 수 있는 정보:

``` json
{
  "pose_result": {},
  "face_result": {},
  "voice_result": {},
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

``` python
stretch_check() -> PoseResult
face_check() -> FaceResult
voice_check() -> VoiceResult

get_baseline(data_type: str) -> BaselineResult
get_history(data_type: str, days: int) -> HistoryResult
save_measurement(result) -> SaveResult

retry_measurement(tool_name: str, reason: str) -> RetryResult
ask_user(question: str) -> UserResponse
contact_guardian(message: str) -> ActionResult
finish_check(message: str) -> ActionResult
```

실제 함수명이 기존 코드와 다르면 기존 구조를 우선하고 문서만 일치하도록
업데이트한다.

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

``` text
data/
├── baseline/
│   ├── pose_baseline.json
│   ├── face_baseline.json
│   └── voice_baseline.json
└── history/
    └── YYYY-MM-DD.json
```

### pose baseline

가능한 특징: - left_arm_angle - right_arm_angle - arm_angle_difference -
left_arm_height - right_arm_height - measurement_quality

### face baseline

가능한 특징: - landmark-derived asymmetry values - mouth asymmetry -
other implemented facial asymmetry values - measurement_quality

### voice baseline

구현 가능한 범위에서: - speech_rate - silence_ratio - duration - MFCC
summary - measurement_quality

데이터가 없는 필드를 임의로 생성하지 말 것.

## 6. Core Decision Principle

고정된 모든 검사를 항상 실행하지 않는다.

예:

``` text
Pose normal + high quality
-> finish

Pose changed + high quality
-> Agent selects additional check

Pose quality low
-> retry pose

Pose changed
+ Face normal
+ Voice quality low
-> retry voice instead of treating voice as abnormal
```

단순 threshold 계산은 일반 코드가 담당해도 된다.

Agent의 핵심 역할은 다음을 종합하여 다음 행동을 선택하는 것이다.

``` text
measurement result
+ quality
+ personal baseline
+ recent history
+ available tools
+ user context
```

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

Agent 영역에서 보여줄 것: - 현재 단계 - 호출한 Tool - Tool 결과 요약 -
다음 행동 - 사용자에게 필요한 안내

내부 chain-of-thought는 표시하지 않는다.

### Pose Overlay

- 가장 최근의 유효한 baseline/history 포즈 이미지를 불러온다.
- 현재 카메라 화면 위에 투명도를 적용하여 겹쳐 표시한다.
- 사용자가 이전 자세와 현재 자세를 쉽게 맞출 수 있도록 한다.
- 이미지가 없으면 해당 기능은 비활성화하고 일반 카메라 화면만 표시한다.
- 구현 안정성이 더 높은 경우 실제 이미지를 겹치는 대신 최근 landmark skeleton을 반투명하게 표시할 수 있다.


## 9. Known Bugs / Issues

### ISSUE-001 Camera

증상: - 카메라 화면이 UI에 표시되지 않음.

조사 순서: 1. camera device open 여부 2. frame read 성공 여부 3. frame
conversion 여부 4. UI rendering 여부

입력 문제와 표시 문제를 분리하여 디버깅할 것.

### ISSUE-002 Voice

현재 STT 중심 방식은 재검토한다.

목표: - 텍스트 내용보다 음향 변화 특징을 사용할 수 있는지 검토 - speech
rate - silence ratio - duration - MFCC 등

구현 시간이 부족하면 최소 기능부터 구현하고 TODO를 명확히 남긴다.

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

### PROCEDURE 1 - Existing Project Inspection

목표: - 현재 프로젝트 구조와 실행 경로를 파악한다.

해야 할 일: 1. 전체 디렉터리 구조 확인 2. entry point 확인 3. camera /
pose / face / voice / UI 관련 파일 확인 4. 현재 데이터 흐름 작성 5.
변경이 필요한 파일 후보 제시

완료 후: - 코드를 대규모 수정하지 말 것. - 발견 내용을 짧게 보고하고
STOP. - Raspberry Pi 테스트가 필요한 경우 정확한 실행 명령과 확인 항목만
제공.

### PROCEDURE 2 - Pose Reliability

목표: - stretch/pose 핵심 기능을 실제 환경에서 안정화한다.

구현: - frame 획득 확인 - landmark 검출 확인 - measurement
quality/confidence - 실패 시 다음 단계 진행 차단 - retry 처리 - pose
result 구조화

테스트: 1. 정상 자세 2. 카메라에서 벗어남 3. 팔 일부가 가려짐

완료 후 STOP.

### PROCEDURE 3 - Personal Pose Baseline

목표: - 개인 baseline 저장/로드/비교 기능 구현.

구현: - 여러 정상 측정값 저장 가능 - baseline summary 계산 - current vs
baseline 변화량 반환 - history 저장

테스트: 1. baseline 없음 2. 정상 범위 3. 큰 좌우 차이

완료 후 STOP.

### PROCEDURE 4 - Agent Orchestrator

목표: - Agent가 측정 결과를 받고 다음 Tool/행동을 선택하도록 연결.

최소 행동: - finish - retry pose - request face check - request voice
check - request history - ask user

중요: - Agent가 측정값 자체를 만들어내지 않게 한다. - Tool 결과만 근거로
사용한다. - Tool 호출과 짧은 reason을 로그/UI에 표시한다.

테스트: 1. normal pose -\> finish 2. changed pose -\> additional tool 3.
low quality -\> retry

완료 후 STOP.

### PROCEDURE 5 - Face Tool

목표: - MediaPipe Face Landmarker 기반 얼굴 특징 측정 Tool 연결.

구현: - landmark detection - implemented asymmetry feature - quality -
baseline comparison - failure handling

완료 후 STOP.

### PROCEDURE 6 - Voice Tool

목표: - 가능한 범위에서 음향 특징 기반 Tool 구현.

우선순위: 1. recording success 2. duration 3. silence ratio 4. speech
rate if feasible 5. MFCC if feasible

시간 부족 시 안정적인 최소 기능을 우선한다.

완료 후 STOP.

### PROCEDURE 7 - Integrated Agent Scenarios

반드시 테스트: 1. 정상 2. 변화 감지 3. 측정 실패

각 테스트마다 기록:

``` text
Input
Expected
Actual
Problem
Fix
Retest
```

완료 후 STOP.

### PROCEDURE 8 - Final Documentation

사용자 승인 후 다음 문서를 생성/갱신한다.

`README.md` 또는 `PROGRAM_GUIDE.md`

포함: - 프로젝트 목적 - 안전 범위 - architecture - directory/file
roles - installation - execution - Agent flow - Tool descriptions - data
format - configuration - error handling - test scenarios - known
limitations - future improvements

## 11. Definition of Done

핵심 데모가 다음을 실제로 보여주면 성공:

``` text
real camera input
-> pose measurement
-> personal baseline comparison
-> Agent decision
-> dynamic Tool/action selection
-> measurement failure retry
-> visible result in UI
```

Face/Voice가 모두 완벽하지 않더라도 핵심 Agent 경로가 실제로 안정적으로
작동하는 것을 우선한다.

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
