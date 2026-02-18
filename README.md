# Diary Schedule Assistant
<img width="956" height="503" alt="화면 캡처 2026-02-16 220240" src="https://github.com/user-attachments/assets/27167360-929a-4b56-a8d8-6c27b88b1670" />

자연어로 일정을 입력하면 저장/알림/공부계획 자동 생성까지 해주는 로컬 AI 일정 비서입니다.  
CLI와 GUI를 모두 지원합니다.

## 핵심 기능

- 자연어 일정 등록
  - 예: `20일 9시 면접, 1시 시험`
- 남은 일수 즉시 계산
  - 예: `4월 9일 파이널 프로젝트 발표까지 며칠 남았어?`
- 공부계획 자동 생성
  - 예: `영어 공부계획 14일, 하루 2시간`
- 시험일까지 역산 배분
  - 예: `6월 30일 시험까지 역산 배분, 수학 40 영어 30 국어 30, 하루 4시간`
- 데스크톱 알림 + (선택) 텔레그램/카카오 알림
- 대화 메모리 저장/복원 (`chat_memory.json`)

## 말하는 방법 가이드 (중요)

자연어를 자유롭게 말해도 되지만, 아래 패턴으로 말하면 정확도가 가장 높습니다.

### 1) 일정 등록 패턴

- 기본: `N일 N시 일정명`
- 여러 개: `20일 9시 면접, 1시 시험. 21일 코딩테스트`
- 오전/오후: `20일 오후 1시 시험`

권장 표현:
- `20일 9시 면접`
- `21일 오후 2시 프로젝트 발표`

남은 일수 질문:
- `4월 9일 발표까지 며칠 남았어?`
- `2026-04-09까지 몇일 남음?`

### 2) 공부계획 패턴

- `과목 공부계획 N일, 하루 N시간`
- 예: `영어 공부계획 14일, 하루 2시간`

시간/일수 생략 시:
- 일수 기본값: 7일
- 하루 공부시간 기본값: 2시간

### 3) 시험 역산 배분 패턴

- 가중치 방식: `6월 30일 시험까지 역산 배분, 수학 40 영어 30 국어 30, 하루 4시간`
- 총시간 방식: `2026-07-15 시험까지 배분, 수학 20시간 영어 15시간`

해석 규칙:
- `수학 40` 같은 숫자는 비중(가중치)
- `수학 20시간`은 과목별 총 공부시간

### 4) 잘 안 되는 케이스

- 날짜/시간 없이 너무 추상적인 문장
- 과목/시간 단위가 섞여 모호한 문장

이럴 땐 한 줄에 핵심 3개만 넣으면 정확도가 올라갑니다:
- `언제(날짜/시간) + 무엇(일정명/과목) + 얼마나(시간/비중)`

## 설치

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

실행 정책 이슈가 있으면(Windows PowerShell):

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

## CLI 사용법

### 1) 한 줄 명령

```powershell
python assistant.py ask "20일 9시 면접, 1시 시험"
python assistant.py ask "영어 공부계획 14일, 하루 2시간"
python assistant.py ask "6월 30일 시험까지 역산 배분, 수학 40 영어 30 국어 30, 하루 4시간"
```

### 2) 대화형 모드

```powershell
python assistant.py chat
```

대화형에서 자주 쓰는 명령:
- `list`
- `remove 3`
- `memory`
- `memory save`
- `memory load`
- `memory reset`
- `exit`

### 3) 알림 루프 실행

```powershell
python assistant.py run
```

### 4) 알림 테스트

```powershell
python assistant.py notify-test
```

## GUI 사용법

```powershell
python gui.py
```

폴더 이동 없이 실행하려면 아래 파일 더블클릭:
- `launch_gui.bat`
- `launch_chat.bat`
- `launch_notifier.bat`

추천:
1. `launch_gui.bat` 우클릭 -> `바로 가기 만들기`
2. 만든 바로가기를 바탕화면으로 이동
3. 이후에는 바탕화면 아이콘으로 실행

### GUI 기능 요약

- 좌측: 채팅 입력/응답, 메모리 상태
- 우측: `All Events`, `Today`, `Week Calendar` 뷰
- `All/Today` 표에 `D-day` 컬럼 표시
- 일정 우선순위 색상 표시
  - 시험/코테, 면접, 공부 자동 태깅
- 주간 뷰 스티커
  - 평일 `✿`, 토요일 `♡`, 일요일 `♥`
- 테마 전환
  - `Princess`, `Mint`, `Simple`
- 알림 버튼
  - `Start Notifier`, `Stop Notifier`
- 전체 초기화
  - `Reset` 시 메모리 + 채팅 + 일정 전체 삭제(확인창)

## 이미지 커스터마이징 (GUI)

1. `Use My Image` 클릭
2. PNG 파일 선택
3. `Edit Image` 클릭해서 조정 패널 열기
4. 아래 항목 조절
   - `Scale %` (확대/축소)
   - `Offset X`, `Offset Y` (위치 이동)
   - `Canvas W/H` + `Apply Size` (표시 영역 크기)
5. 조절 후 `Done`으로 패널 닫기

참고:
- 이미지 파일은 `assets/user_illustration.png`로 저장됩니다.
- 조절값은 `gui_settings.json`에 저장되어 다음 실행에도 유지됩니다.

## 텔레그램/카카오 연동 (선택)

### Telegram

```powershell
$env:TELEGRAM_BOT_TOKEN="123456:ABC..."
$env:TELEGRAM_CHAT_ID="123456789"
```

### KakaoTalk

```powershell
$env:KAKAO_ACCESS_TOKEN="kakao_user_access_token"
```

## 프로젝트 파일

- `assistant.py`: CLI, 파싱, 계획 생성, 알림/외부 연동
- `gui.py`: 데스크톱 GUI
- `requirements.txt`: 의존성
- `schedule.db`: 일정 DB (런타임 생성)
- `chat_memory.json`: 대화 메모리 저장 파일 (런타임 생성)
- `gui_settings.json`: GUI 설정 저장 파일 (런타임 생성)

## 스크린샷 추가 예정

원하면 다음에 네가 주는 이미지를 `docs/` 폴더에 넣고 README에 바로 배치해줄게요.
