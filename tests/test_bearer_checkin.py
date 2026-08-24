import json
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import checkin  # noqa: E402
from utils.config import AccountConfig, AppConfig  # noqa: E402

SELF_OK = {'success': True, 'data': {'id': 42, 'quota': 5_000_000, 'used_quota': 1_000_000}}
SELF_BAD = {'success': False, 'message': 'unauthorized'}
STATS_NOT_YET = {'success': True, 'data': {'stats': {'checked_in_today': False}}}
STATS_DONE = {'success': True, 'data': {'stats': {'checked_in_today': True}}}


class FakeResponse:
	def __init__(self, payload, status=200):
		self.status_code = status
		self._payload = payload

	def json(self):
		if isinstance(self._payload, Exception):
			raise self._payload
		return self._payload

	@property
	def text(self):
		return json.dumps(self._payload, ensure_ascii=False)


class FakeClient:
	"""Matches routes by substring of "<METHOD> <url>" and records每次调用的头。"""

	def __init__(self, routes):
		self.routes = routes
		self.calls: list[tuple[str, str, dict]] = []
		self.cookies: dict = {}

	def __enter__(self):
		return self

	def __exit__(self, *exc):
		return False

	def _resolve(self, method, url, headers):
		self.calls.append((method, url, dict(headers or {})))
		for key, payload in self.routes.items():
			if key in f'{method} {url}':
				# 路由值可以直接给 FakeResponse，用来模拟非 200 的状态码
				return payload if isinstance(payload, FakeResponse) else FakeResponse(payload)
		raise AssertionError(f'unrouted request: {method} {url}')

	def get(self, url, headers=None, **kwargs):
		return self._resolve('GET', url, headers)

	def post(self, url, headers=None, **kwargs):
		return self._resolve('POST', url, headers)


def run(monkeypatch, routes, account, provider_name='gorouter', **kwargs):
	client = FakeClient(routes)
	monkeypatch.setattr(checkin.httpx, 'Client', lambda **_: client)
	provider = AppConfig.load_from_env().get_provider(provider_name)
	result = checkin.run_bearer_check_in(account, account.name, provider, **kwargs)
	return result, client


def gorouter_account():
	return AccountConfig(cookies=None, provider='gorouter', name='GoRouter', access_token='tok-abc', api_user='21047')


def tabitoken_account():
	return AccountConfig(cookies=None, provider='tabitoken', name='TaBiAI', access_token='tok-xyz')


def justdowork_account():
	return AccountConfig(cookies=None, provider='justdowork', name='JustDoWork', access_token='tok-jdw')


def wong_account():
	return AccountConfig(cookies=None, provider='wong', name='WONG', access_token='tok-wong', api_user='8039')


def test_rejected_access_token_aborts_before_check_in(monkeypatch):
	routes = {'GET https://gorouter.app/api/user/self': SELF_BAD}

	(success, before, after, site_key), client = run(monkeypatch, routes, gorouter_account())

	assert success is False
	assert site_key is None
	assert not [c for c in client.calls if c[0] == 'POST']


def test_already_checked_in_skips_the_post(monkeypatch):
	routes = {
		'GET https://gorouter.app/api/user/self': SELF_OK,
		'GET https://gorouter.app/api/user/checkin?month=': STATS_DONE,
	}

	(success, before, after, site_key), client = run(monkeypatch, routes, gorouter_account())

	assert success is True
	assert site_key is None
	assert before and after
	assert not [c for c in client.calls if c[0] == 'POST']


def test_turnstile_required_reports_site_key_from_status(monkeypatch):
	routes = {
		'GET https://gorouter.app/api/user/self': SELF_OK,
		'GET https://gorouter.app/api/user/checkin?month=': STATS_NOT_YET,
		'POST https://gorouter.app/api/user/checkin': {'success': False, 'message': 'Turnstile token 为空'},
		'GET https://gorouter.app/api/status': {'success': True, 'data': {'turnstile_site_key': '0xLIVEKEY'}},
	}

	(success, before, after, site_key), client = run(monkeypatch, routes, gorouter_account())

	assert success is False
	assert site_key == '0xLIVEKEY'

	status_calls = [c for c in client.calls if '/api/status' in c[1]]
	assert len(status_calls) == 1
	headers = status_calls[0][2]
	# /api/status 是公开接口，不该带上访问令牌；但必须带浏览器 UA，否则 Cloudflare 403
	assert not any(k.lower() == 'authorization' for k in headers)
	assert 'Mozilla' in headers.get('User-Agent', '')


def test_turnstile_token_is_url_encoded_into_the_query(monkeypatch):
	routes = {
		'GET https://gorouter.app/api/user/self': SELF_OK,
		'GET https://gorouter.app/api/user/checkin?month=': STATS_NOT_YET,
		'POST https://gorouter.app/api/user/checkin': {
			'success': True,
			'data': {'quota_awarded': 4_000_000},
		},
	}

	(success, _, _, site_key), client = run(
		monkeypatch, routes, gorouter_account(), turnstile_token='tok/with+special=chars'
	)

	assert success is True
	assert site_key is None
	posted = [c[1] for c in client.calls if c[0] == 'POST']
	assert posted and 'turnstile=tok%2Fwith%2Bspecial%3Dchars' in posted[0]


def test_already_checked_in_message_counts_as_success(monkeypatch):
	routes = {
		'GET https://gorouter.app/api/user/self': SELF_OK,
		'GET https://gorouter.app/api/user/checkin?month=': {'success': False, 'message': 'nope'},
		'POST https://gorouter.app/api/user/checkin': {'success': False, 'message': '今日已签到'},
	}

	(success, _, _, site_key), _ = run(monkeypatch, routes, gorouter_account())

	assert success is True
	assert site_key is None


def test_real_error_stays_a_failure(monkeypatch):
	routes = {
		'GET https://gorouter.app/api/user/self': SELF_OK,
		'GET https://gorouter.app/api/user/checkin?month=': {'success': False, 'message': 'nope'},
		'POST https://gorouter.app/api/user/checkin': {'success': False, 'message': '签到功能未启用'},
	}

	(success, _, _, site_key), _ = run(monkeypatch, routes, gorouter_account())

	assert success is False
	assert site_key is None


def test_api_user_header_sent_only_when_configured(monkeypatch):
	# gorouter (NewAPI rc.21) 缺 New-Api-User 会 401，必须连同 bearer 一起发
	routes = {'GET https://gorouter.app/api/user/self': SELF_BAD}
	_, client = run(monkeypatch, routes, gorouter_account())
	headers = client.calls[0][2]
	assert headers['Authorization'] == 'Bearer tok-abc'
	assert headers['new-api-user'] == '21047'

	# tabitoken (rc.23) 不需要该头，未配置 api_user 时不应凭空加上
	routes = {'GET https://tabitoken.com/api/user/self': SELF_BAD}
	_, client = run(monkeypatch, routes, tabitoken_account(), provider_name='tabitoken')
	headers = client.calls[0][2]
	assert headers['Authorization'] == 'Bearer tok-xyz'
	assert not any(k.lower() == 'new-api-user' for k in headers)


def test_no_hardcoded_accept_encoding(monkeypatch):
	"""声明 br/zstd 但环境缺解码库时，httpx 会拿压缩字节解 UTF-8 而崩。"""
	routes = {'GET https://gorouter.app/api/user/self': SELF_BAD}

	_, client = run(monkeypatch, routes, gorouter_account())

	headers = client.calls[0][2]
	assert not any(k.lower() == 'accept-encoding' for k in headers)


def test_justdowork_uses_the_same_bearer_flow(monkeypatch):
	"""JustDoWork（api.justwoker.icu）的面板接口与 tabitoken 同形：Bearer 认证、/api/user/checkin、免 New-Api-User。"""
	routes = {
		'GET https://api.justwoker.icu/api/user/self': SELF_OK,
		'GET https://api.justwoker.icu/api/user/checkin?month=': STATS_DONE,
	}

	(success, before, after, site_key), client = run(
		monkeypatch, routes, justdowork_account(), provider_name='justdowork'
	)

	assert success is True
	assert site_key is None
	assert before and after
	# 已签到就不该再 POST，省掉整个浏览器取 Turnstile 的流程
	assert not [c for c in client.calls if c[0] == 'POST']
	headers = client.calls[0][2]
	assert headers['Authorization'] == 'Bearer tok-jdw'
	assert not any(k.lower() == 'new-api-user' for k in headers)


def test_wong_checks_in_without_a_status_precheck(monkeypatch):
	"""WONG 公益站免 Turnstile，但状态查询不带 stats，所以直接 POST，且要 New-Api-User 头。"""
	routes = {
		'GET https://wzw.pp.ua/api/user/self': SELF_OK,
		'POST https://wzw.pp.ua/api/user/checkin': {
			'success': True,
			'data': {'checked_in': True, 'quota': 13_415_360},
		},
	}

	(success, before, after, site_key), client = run(monkeypatch, routes, wong_account(), provider_name='wong')

	assert success is True
	assert site_key is None
	assert before and after
	# checkin_status_path 为空，不该白发一次状态查询
	assert not [c for c in client.calls if 'month=' in c[1]]
	headers = client.calls[0][2]
	assert headers['Authorization'] == 'Bearer tok-wong'
	assert headers['new-api-user'] == '8039'


def test_wong_duplicate_check_in_counts_as_success(monkeypatch):
	"""没有状态预检，重复签到全靠这句服务端文案兜底。"""
	routes = {
		'GET https://wzw.pp.ua/api/user/self': SELF_OK,
		'POST https://wzw.pp.ua/api/user/checkin': {'success': False, 'message': '今天已经签到过啦'},
	}

	(success, _, _, site_key), _ = run(monkeypatch, routes, wong_account(), provider_name='wong')

	assert success is True
	assert site_key is None


def test_site_outage_is_not_blamed_on_the_access_token(monkeypatch):
	"""站点 5xx（GoRouter 曾整天 522）不能报成令牌失效，否则会被引去白换令牌。"""
	routes = {'GET https://gorouter.app/api/user/self': FakeResponse({}, status=522)}

	(success, before, after, site_key), client = run(monkeypatch, routes, gorouter_account())

	assert success is False
	assert site_key is None
	assert not [c for c in client.calls if c[0] == 'POST']
	# 通知里给的是「站点故障」，不是 raw 英文报错
	assert before is not None
	assert before['error'] == '站点暂时故障（HTTP 522），非令牌问题'


def test_classify_user_info_failure_separates_site_problems_from_token_problems():
	cloudflare = checkin.classify_user_info_failure('Failed to get user info: HTTP 403')
	assert cloudflare is not None and 'Cloudflare' in cloudflare[0]

	outage = checkin.classify_user_info_failure('Failed to get user info: HTTP 502')
	assert outage is not None and 'HTTP 502' in outage[2]

	# 连不上时压根没有 HTTP 状态码，同样不是令牌的问题
	unreachable = checkin.classify_user_info_failure('Failed to get user info: All connection attempts fail...')
	assert unreachable is not None and '无法连接' in unreachable[2]

	# 这两种才该怀疑令牌：明确的 401，以及 200 但 success=false
	assert checkin.classify_user_info_failure('Failed to get user info: HTTP 401') is None
	assert checkin.classify_user_info_failure('Failed to get user info: HTTP 200') is None
