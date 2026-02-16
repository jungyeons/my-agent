# Local AI Schedule Assistant

Natural-language Korean scheduler with:
- desktop alerts
- interactive chat mode
- auto study-plan generation
- exam countdown workload distribution
- optional Telegram/KakaoTalk notifications

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Quick commands

```powershell
python assistant.py ask "20일에 9시에는 면접이 있고 1시에는 시험이 있어"
python assistant.py ask "영어 공부계획 14일, 하루 2시간"
python assistant.py ask "6월 30일 시험까지 역산 배분, 수학 40 영어 30 국어 30, 하루 4시간"
python assistant.py list
python assistant.py run
```

## Interactive chat mode

```powershell
python assistant.py chat
```

## Desktop GUI mode

```powershell
python gui.py
```

GUI features:
- chat-like input
- auto memory apply/save/load/reset
- event tabs: all events / today / week calendar
- reset clears memory + chat + all events (with confirmation)
- event table + delete selected (all/today tab)
- notifier start/stop button

Chat examples:
- `20일 9시 면접, 1시 시험`
- `영어 공부계획 10일, 하루 3시간`
- `6월 30일 시험까지 역산 배분, 수학 40 영어 30 국어 30, 하루 4시간`
- `list`
- `remove 3`
- `memory`
- `memory save`
- `memory load`
- `memory reset`
- `exit`

Memory behavior in `chat`:
- Remembers recent exam date, subjects, daily study hours, and study goal.
- If next message omits some fields, it auto-fills from memory.
- Shows applied text with `(using memory) ...` when auto-filled.
- Memory is persisted to `chat_memory.json` and auto-loaded on next `chat` start.

## Exam countdown distribution behavior

Input style:
- `6월 30일 시험까지 역산 배분, 수학 40 영어 30 국어 30, 하루 4시간`
- `2026-07-15 시험까지 배분, 수학 20시간 영어 15시간`

Rules:
- Builds daily events from tomorrow to day before exam.
- Adds an exam-day reminder event at `09:00`.
- If subject values are weights (e.g. `수학 40`), daily total time (default `3h`) is split proportionally.
- If subject values are total hours (e.g. `수학 20시간`), each subject is spread across remaining days.

## Telegram / KakaoTalk notifications

`assistant.py run` and `assistant.py notify-test` send desktop notifications always, and also send Telegram/Kakao when env vars are set.

### Telegram

Set env vars:

```powershell
$env:TELEGRAM_BOT_TOKEN="123456:ABC..."
$env:TELEGRAM_CHAT_ID="123456789"
```

### KakaoTalk (나에게 보내기 API)

Set env var:

```powershell
$env:KAKAO_ACCESS_TOKEN="kakao_user_access_token"
```

Notes:
- Kakao access token must have Talk Message permission.
- Token refresh flow is not automated in this MVP.

## Useful commands

```powershell
python assistant.py notify-test
python assistant.py remove 1
python assistant.py list
python gui.py
```
