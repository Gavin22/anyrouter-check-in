import json

from utils.config import load_accounts_config

COOKIE_ACCOUNT = {'name': 'AnyRouter', 'provider': 'anyrouter', 'cookies': {'session': 'abc'}, 'api_user': '89519'}
EMAIL_ACCOUNT = {'name': 'Agent Router', 'provider': 'agentrouter', 'email': 'a@b.com', 'password': 'pw'}
BEARER_ACCOUNT = {'name': 'GoRouter', 'provider': 'gorouter', 'access_token': 'tok-123'}


def test_existing_account_shapes_still_load(monkeypatch):
	monkeypatch.setenv('ANYROUTER_ACCOUNTS', json.dumps([COOKIE_ACCOUNT, EMAIL_ACCOUNT]))

	accounts = load_accounts_config()

	assert accounts is not None
	assert len(accounts) == 2
	assert accounts[0].cookies == {'session': 'abc'}
	assert accounts[0].api_user == '89519'
	assert accounts[0].access_token is None
	assert accounts[1].has_login_credentials() is True
	assert accounts[1].has_access_token() is False


def test_access_token_account_loads_without_cookies_or_api_user(monkeypatch):
	monkeypatch.setenv('ANYROUTER_ACCOUNTS', json.dumps([BEARER_ACCOUNT]))

	accounts = load_accounts_config()

	assert accounts is not None
	assert len(accounts) == 1
	assert accounts[0].provider == 'gorouter'
	assert accounts[0].access_token == 'tok-123'
	assert accounts[0].has_access_token() is True
	assert accounts[0].has_login_credentials() is False


def test_mixed_accounts_all_load(monkeypatch):
	"""新增 bearer 账号不能让现有 cookie / 邮箱密码账号一起解析失败。"""
	monkeypatch.setenv(
		'ANYROUTER_ACCOUNTS',
		json.dumps([COOKIE_ACCOUNT, EMAIL_ACCOUNT, BEARER_ACCOUNT]),
	)

	accounts = load_accounts_config()

	assert accounts is not None
	assert len(accounts) == 3
	assert [a.provider for a in accounts] == ['anyrouter', 'agentrouter', 'gorouter']


def test_account_without_any_credential_is_rejected(monkeypatch):
	monkeypatch.setenv('ANYROUTER_ACCOUNTS', json.dumps([{'name': 'Broken', 'provider': 'gorouter'}]))

	assert load_accounts_config() is None


def test_account_with_empty_access_token_is_rejected(monkeypatch):
	monkeypatch.setenv('ANYROUTER_ACCOUNTS', json.dumps([{'name': 'Broken', 'access_token': ''}]))

	assert load_accounts_config() is None


def test_missing_env_returns_none(monkeypatch):
	monkeypatch.delenv('ANYROUTER_ACCOUNTS', raising=False)

	assert load_accounts_config() is None
