# chat-bridge-OCI

[English](README.md) / [한국어](README-kr.md)

OpenAI Secure MCP Tunnel을 통해 ChatGPT에서 Oracle Cloud(OCI) 인스턴스를 관리합니다.
MCP 도구는 `run_command` 하나이며, **root 권한**으로 명령을 실행합니다.
기본 실행 경로는 `/`이고 별도의 에이전트 작업 폴더는 필요하지 않습니다.
파일시스템 샌드박스가 아니므로 부트 볼륨 백업 같은 복구 수단을 준비해 두세요.

## 설치

필요한 환경은 Ubuntu 24.04 이상 또는 Debian 12 이상, Python 3.11 이상,
systemd, `git`, root 또는 sudo 권한입니다. Linux amd64와 arm64를 지원합니다.

먼저 [Secure MCP Tunnel](https://platform.openai.com/settings/organization/tunnels)과
런타임 API 키를 준비하세요. ChatGPT에서 사용하려면 해당 터널을 사용하는 앱도
ChatGPT에 설정되어 있어야 합니다.

```bash
git clone https://github.com/highsun9941/chat-bridge-OCI.git
bash chat-bridge-OCI/bootstrap.sh
```

실행 후 다음 두 값을 순서대로 입력합니다.

1. **터널 ID**: `tunnel_...` 형태의 식별자입니다.
2. **런타임 API 키**: 입력하는 값은 화면에 표시되지 않습니다.

bootstrap은 필요할 때 sudo로 권한을 올립니다. 인스턴스에서의 설치는
위 두 명령과 두 값 입력으로 완료됩니다.

자동화할 때는 `OPENAI_TUNNEL_ID`와 `CONTROL_PLANE_API_KEY`를 환경 변수로
안전하게 전달하세요. 기본 인증값은 없으며 `.env` 파일을 자동으로 읽지 않습니다.

## 설치 결과

bootstrap은 애플리케이션과 최신 공식
[OpenAI tunnel-client](https://github.com/openai/tunnel-client) 릴리스를 설치합니다.
릴리스에 SHA-256이 제공되면 다운로드한 파일을 검증합니다.
다음 두 서비스는 부팅 시 자동으로 시작합니다.

| 서비스 | 실행 사용자 | 인스턴스 내부 주소 |
| --- | --- | --- |
| `chat-bridge-oci.service` | `root` | `127.0.0.1:8000/mcp` |
| `chat-bridge-oci-tunnel.service` | `tunnelclient` | `127.0.0.1:8080/readyz` |

터널은 외부로 나가는 HTTPS 연결을 사용합니다. 인바운드 8000 포트를 열거나
MCP를 외부 주소에 바인딩하지 마세요.
애플리케이션은 `/opt/chat-bridge-OCI`에 설치됩니다.
터널 인증값은 `/etc/chat-bridge-oci-tunnel/tunnel.env`에 저장되며,
소유자는 `root:tunnelclient`, 권한은 `0640`입니다. 인증값을 출력하거나 커밋하지 마세요.

**2026-10-04**에 실제 운영 중인 OCI Ubuntu 24.04 arm64 인스턴스에서 확인한 결과입니다.
당시 버전은 Python 3.12.3, MCP 2.2.0, tunnel-client 0.0.15였습니다.

| 확인 항목 | 실제 결과 |
| --- | --- |
| 서비스 상태 | 둘 다 `active`, `enabled` |
| MCP 도구 | `run_command` 하나만 노출 |
| `run_command(["id", "-u"])` | 종료 코드 `0`, 표준 출력 `0` — root |
| `run_command(["pwd"])` | 종료 코드 `0`, 표준 출력 `/` |
| `/healthz` / `/readyz` | HTTP `200`, 응답 `live` / `ready` |
| 부팅 순서 | MCP 프로토콜 검사가 끝난 뒤 터널 시작 |

위 버전은 확인 당시의 설치 상태를 기록한 것입니다. 이후 설치에서는 의존성에
선언된 버전 범위와 최신 tunnel-client 릴리스를 사용합니다.

## 업데이트와 상태 확인

복제한 저장소 디렉터리에서 실행합니다.

```bash
git pull --ff-only
bash bootstrap.sh
```

같은 터널 ID와 런타임 API 키를 다시 입력하세요.
bootstrap은 설치 파일을 갱신하고 터널을 중지한 뒤 MCP와 터널을 순서대로 재시작합니다.
MCP가 시작할 때마다 최대 60초 동안 연결과 도구 목록을 확인하고,
`run_command` 하나만 노출되는 검사가 통과해야 터널이 시작됩니다.
터널에도 `MCP_STARTUP_WAIT_TIMEOUT=60s`를 설정합니다.

```bash
systemctl is-active chat-bridge-oci.service chat-bridge-oci-tunnel.service
systemctl is-enabled chat-bridge-oci.service chat-bridge-oci-tunnel.service
systemctl show chat-bridge-oci.service -p User -p Group
curl -fsS http://127.0.0.1:8080/healthz
curl -fsS http://127.0.0.1:8080/readyz
sudo /opt/chat-bridge-OCI/.venv/bin/python /opt/chat-bridge-OCI/smoke_test.py
```

두 서비스가 `active`·`enabled`이고, MCP 실행 사용자가 root인지 확인하세요.
HTTP 검사는 둘 다 성공하고, 도구 목록에는 `run_command`만 나와야 합니다.
문제가 있으면 다음 명령으로 로그를 확인합니다.

```bash
sudo journalctl -u chat-bridge-oci.service -u chat-bridge-oci-tunnel.service -n 150 --no-pager
```

bootstrap은 기존 systemd 추가 설정(drop-in)을 보존합니다.
기존 설치가 예상과 다르게 동작하면 `systemctl cat 서비스이름`으로 추가 설정을 확인하세요.

실제 확인한 환경에서는 로컬 MCP 서버가 OAuth 메타데이터를 제공하지 않아
`OAuth discovery failed` 경고가 남았습니다. 이때 `/health/oauth` 진단은
`status: ok`, `state: not_advertised`였고 `/readyz`도 HTTP `200`이었습니다.
이 경고는 준비 상태와 함께 판단하세요.

## 명령 인터페이스와 설정

`run_command(argv, cwd=".", timeout_seconds=120)`은 명령과 인자를 배열로 받아 실행합니다.
예를 들어 `["systemctl", "status", "docker", "--no-pager"]`를 전달합니다.
API의 기본 인자 `cwd="."`는 설치된 서비스에서 `/`로 해석됩니다.
상대 경로도 `/`를 기준으로 해석하며 절대 경로도 사용할 수 있습니다.

결과에는 `argv`, `cwd`, `exit_code`, `stdout`, `stderr`, `timed_out`, `truncated`가 들어갑니다.
시간을 초과하면 `exit_code`는 `null`이며, 그때까지 수집한 출력도 반환합니다.

Python 서버는 다음 환경 변수를 읽습니다. 설치된 서비스에는 systemd 추가 설정을
사용하고, 로컬 개발에서는 실행할 때 환경 변수를 지정하세요.

| 환경 변수 | 기본값 |
| --- | --- |
| `MCP_HOST` / `MCP_PORT` | `127.0.0.1` / `8000` — 호스트는 loopback 유지 |
| `MAX_COMMAND_TIMEOUT` | `600`초 — 기본 설정에서 요청 시간을 1~600초로 제한 |
| `MAX_COMMAND_OUTPUT` | 표준 출력·표준 오류 각각 `200000`자 |
| `CHAT_BRIDGE_EXTRA_ENV_KEYS` | 비어 있음 — 자식 명령에 전달할 추가 환경 변수 이름을 쉼표로 구분 |

자식 명령에는 선택된 환경 변수만 전달합니다.
MCP 연결 검사 스크립트는 별도로 `MCP_URL`을 읽으며 기본값은 `http://127.0.0.1:8000/mcp`입니다.
MCP 주소를 바꾸면 이 검사 주소와 터널의 `MCP_SERVER_URL`도 같은 주소로 맞춰야 합니다.

## 로컬 개발

저장소 디렉터리에서 가상 환경을 사용합니다.
아래 검사에는 터널 키나 root 권한이 필요하지 않습니다.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m unittest discover -s tests -v
bash -n bootstrap.sh
```

현재 사용자 권한으로 서버를 실행하려면 다음 명령을 사용하세요.

```bash
.venv/bin/chat-bridge-oci
```

다른 터미널에서 `.venv/bin/python smoke_test.py`를 실행하면 연결을 확인할 수 있습니다.
유지보수 원칙은 [AGENTS.md](AGENTS.md)를 참고하세요.
