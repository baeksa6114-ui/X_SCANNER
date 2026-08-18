# X Keyword Crawler

`twikit`을 사용해 X(Twitter)의 공개 게시글을 키워드로 검색하고 CSV와 JSON으로 저장하는 터미널 프로그램입니다.

## 작동 과정

```text
X 인증
→ 검색어, Latest/Top, 최대 수집 개수 입력
→ 검색 결과 페이지 순차 요청
→ 게시글 ID 기준 중복 제거
→ data/tweets.csv와 data/tweets.json 저장
```

페이지 요청 사이에는 랜덤 대기 시간이 적용됩니다. 수집 중 오류가 발생하거나 Ctrl+C로 중단해도 현재까지 수집한 결과를 저장합니다.

## 최초 설치

Windows VS Code의 PowerShell 터미널에서 실행합니다.

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
```

PowerShell에서 가상환경 활성화가 거부되면 다음을 먼저 실행합니다.

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.venv\Scripts\activate
```

## `.env` 설정

예제 파일을 복사합니다.

```powershell
Copy-Item .env.example .env
```

브라우저 쿠키 방식이 권장됩니다. X에 로그인한 브라우저의 개발자 도구에서 `Application → Cookies → https://x.com`으로 이동한 뒤 `auth_token`과 `ct0`의 값을 입력합니다.

```env
X_USERNAME=
X_EMAIL=
X_PASSWORD=
X_AUTH_TOKEN=auth_token_값
X_CT0=ct0_값
```

사용자명과 비밀번호로 로그인하려면 다음처럼 작성합니다. 이메일은 선택사항입니다.

```env
X_USERNAME=at기호를_제외한_사용자명
X_EMAIL=
X_PASSWORD=비밀번호
X_AUTH_TOKEN=
X_CT0=
```

`.env`, 비밀번호, 쿠키 값은 외부에 공유하거나 Git에 업로드하지 마세요.

## 실행

```powershell
python main.py
```

가상환경을 활성화하지 않았다면 다음 명령을 사용합니다.

```powershell
.venv\Scripts\python.exe main.py
```

입력 예시:

```text
검색 키워드 입력: privacy
검색 방식 선택 [1]: 1
최대 수집 개수 [100]: 10
```

검색 방식의 기본값은 `Latest`, 최대 수집 개수의 기본값은 `100`입니다. 결과는 다음 파일에 저장됩니다.

- `data/tweets.csv`
- `data/tweets.json`
