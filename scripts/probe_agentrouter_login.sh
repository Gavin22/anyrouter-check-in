#!/usr/bin/env bash
# 临时诊断：用一次性假凭据探测 AgentRouter 登录接口，判断 runner 出口是否被拦。
# 不涉及任何真实账号密码；AgentRouter 必定返回“用户名或密码错误”。
#
# 判读方式：
#   {"success":false,"message":"用户名或密码错误..."}  -> 站点在该出口工作正常
#   403 / Cloudflare 挑战 / 超时 / 空响应              -> 出口 IP 被拦
#
# 环境变量:
#   PROBE_DOMAIN        探测域名，默认 https://agentrouter.org
#   CHECKIN_PROXY_URL   代理地址（由 setup_mihomo_proxy.sh 写入 GITHUB_ENV）

set -uo pipefail

PROBE_DOMAIN="${PROBE_DOMAIN:-https://agentrouter.org}"
PROXY_URL="${CHECKIN_PROXY_URL:-}"
UA='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36'

# 一次性用户名，确保不会命中任何真实账号
PROBE_USER="probe-$(date +%s)-${RANDOM}"
PROBE_PASS="probe-invalid-000"  # nosec
PROBE_BODY="{\"username\":\"${PROBE_USER}\",\"password\":\"${PROBE_PASS}\"}"

echo "[INFO] Probe domain: ${PROBE_DOMAIN}"
echo "[INFO] Probe username: ${PROBE_USER} (non-existent by construction)"
if [[ -n "${PROXY_URL}" ]]; then
	echo "[INFO] Proxy: ${PROXY_URL}"
else
	echo "[WARN] CHECKIN_PROXY_URL is empty, proxy probes will be skipped"
fi

run_probe() {
	local label="$1" via="$2" method="$3" url="$4"
	local -a args=(-sS --max-time 45 -o /tmp/probe_body.txt -w '%{http_code} %{time_total}')

	if [[ "${via}" == "proxy" ]]; then
		if [[ -z "${PROXY_URL}" ]]; then
			echo "[SKIP] ${label}: no proxy configured"
			return 0
		fi
		args+=(-x "${PROXY_URL}")
	fi

	args+=(-A "${UA}")
	if [[ "${method}" == "POST" ]]; then
		args+=(-X POST -H 'Content-Type: application/json' -H 'Accept: application/json' \
			-H "Origin: ${PROBE_DOMAIN}" -H "Referer: ${PROBE_DOMAIN}/login" --data-raw "${PROBE_BODY}")
	fi

	: > /tmp/probe_body.txt
	local meta
	if meta=$(curl "${args[@]}" "${url}" 2>/tmp/probe_err.txt); then
		echo "[RESULT] ${label}: http=${meta%% *} time=${meta##* }s"
	else
		echo "[RESULT] ${label}: curl failed -> $(tr -d '\n' < /tmp/probe_err.txt | cut -c1-200)"
	fi
	echo "[BODY]   ${label}: $(head -c 400 /tmp/probe_body.txt | tr -d '\r\n')"
}

echo '--- 1. exit IP as seen by the internet ---'
run_probe 'exit-ip via proxy' proxy GET 'https://api.ipify.org?format=json'
run_probe 'exit-ip direct' direct GET 'https://api.ipify.org?format=json'

echo '--- 2. site reachability (no auth needed) ---'
run_probe 'GET /api/status via proxy' proxy GET "${PROBE_DOMAIN}/api/status"
run_probe 'GET /api/status direct' direct GET "${PROBE_DOMAIN}/api/status"

echo '--- 3. login endpoint with throwaway credentials ---'
run_probe 'POST /api/user/login via proxy' proxy POST "${PROBE_DOMAIN}/api/user/login?turnstile="
run_probe 'POST /api/user/login direct' direct POST "${PROBE_DOMAIN}/api/user/login?turnstile="

rm -f /tmp/probe_body.txt /tmp/probe_err.txt
echo '[INFO] Probe finished (diagnostic only, never fails the job)'
exit 0
