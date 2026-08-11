from unittest.mock import ANY, AsyncMock, MagicMock

import pytest

import checkin
from utils.browser import BrowserLoginResult
from utils.config import AccountConfig, AppConfig, ProviderConfig


@pytest.mark.asyncio
async def test_login_with_api_credentials_returns_fresh_session(monkeypatch):
	response = MagicMock()
	response.status_code = 200
	response.json.return_value = {'success': True, 'data': {'id': 47933}}

	client = MagicMock()
	client.cookies = {'acw_tc': 'waf-cookie', 'session': 'fresh-session'}
	client.post = AsyncMock(return_value=response)
	client.__aenter__ = AsyncMock(return_value=client)
	client.__aexit__ = AsyncMock(return_value=None)
	monkeypatch.setattr(checkin.httpx, 'AsyncClient', lambda **kwargs: client)

	provider = ProviderConfig(
		name='agentrouter',
		domain='https://ps.air-outer.com',
		login_api_path='/api/user/login',
		sign_in_path=None,
	)
	result = await checkin.login_with_api_credentials('Agent Router', provider, 'user@example.com', 'secret')

	assert result is not None
	assert result.cookies == {'acw_tc': 'waf-cookie', 'session': 'fresh-session'}
	assert result.api_user == '47933'
	client.post.assert_awaited_once_with(
		'https://ps.air-outer.com/api/user/login',
		headers=ANY,
		json={'username': 'user@example.com', 'password': 'secret'},
	)


@pytest.mark.asyncio
async def test_login_with_api_credentials_rejects_missing_session(monkeypatch):
	response = MagicMock()
	response.status_code = 200
	response.json.return_value = {'success': True, 'data': {'id': 47933}}

	client = MagicMock()
	client.cookies = {'acw_tc': 'waf-cookie'}
	client.post = AsyncMock(return_value=response)
	client.__aenter__ = AsyncMock(return_value=client)
	client.__aexit__ = AsyncMock(return_value=None)
	monkeypatch.setattr(checkin.httpx, 'AsyncClient', lambda **kwargs: client)

	provider = ProviderConfig(
		name='agentrouter',
		domain='https://ps.air-outer.com',
		login_api_path='/api/user/login',
		sign_in_path=None,
	)
	result = await checkin.login_with_api_credentials('Agent Router', provider, 'user@example.com', 'secret')

	assert result is None


@pytest.mark.asyncio
async def test_login_with_browser_api_credentials_verifies_user_in_same_session(monkeypatch):
	page = MagicMock()
	page.goto = AsyncMock()
	page.evaluate = AsyncMock(
		return_value={
			'loginStatus': 200,
			'loginSuccess': True,
			'userId': '47933',
			'userStatus': 200,
			'userData': {'id': 47933, 'quota': 257810000, 'used_quota': 0},
		}
	)
	page.context.cookies = AsyncMock(
		return_value=[
			{'name': 'acw_tc', 'value': 'waf-cookie'},
			{'name': 'session', 'value': 'fresh-session'},
		]
	)
	browser = MagicMock()
	browser.new_page = AsyncMock(return_value=page)
	browser.close = AsyncMock()
	monkeypatch.setattr(checkin, 'launch_async', AsyncMock(return_value=browser))
	monkeypatch.setattr(checkin, 'prepare_browser_page', AsyncMock())
	monkeypatch.setattr(checkin, 'wait_for_waf_ready', AsyncMock())

	provider = ProviderConfig(
		name='agentrouter',
		domain='https://ps.air-outer.com',
		login_path='/login',
		login_api_path='/api/user/login',
		sign_in_path=None,
		bypass_method='waf_cookies',
		waf_cookie_names=['acw_tc'],
	)
	result = await checkin.login_with_browser_api_credentials('Agent Router', provider, 'user@example.com', 'secret')

	assert result is not None
	assert result.cookies == {'acw_tc': 'waf-cookie', 'session': 'fresh-session'}
	assert result.api_user == '47933'
	assert result.user_info == {'id': 47933, 'quota': 257810000, 'used_quota': 0}
	page.goto.assert_awaited_once_with('https://ps.air-outer.com/login', wait_until='domcontentloaded')
	browser.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_check_in_account_uses_browser_verified_user_info(monkeypatch):
	provider = ProviderConfig(
		name='agentrouter',
		domain='https://ps.air-outer.com',
		login_api_path='/api/user/login',
		sign_in_path=None,
		bypass_method='waf_cookies',
		waf_cookie_names=['acw_tc'],
	)
	account = AccountConfig(
		cookies=None,
		provider='agentrouter',
		name='Agent Router',
		email='user@example.com',
		password='secret',
	)
	login = AsyncMock(
		return_value=BrowserLoginResult(
			cookies={'session': 'fresh-session'},
			api_user='47933',
			user_info={'id': 47933, 'quota': 257810000, 'used_quota': 250000},
		)
	)
	monkeypatch.setattr(checkin, 'login_with_api_credentials', login)
	request_checkin = MagicMock(side_effect=AssertionError('HTTP fallback must not run'))
	monkeypatch.setattr(checkin, 'run_check_in_requests', request_checkin)

	success, before, after = await checkin.check_in_account(
		account,
		0,
		AppConfig(providers={'agentrouter': provider}),
	)

	assert success is True
	assert (
		before
		== after
		== {
			'success': True,
			'quota': 515.62,
			'used_quota': 0.5,
			'display': ':money: Current balance: $515.62, Used: $0.5',
		}
	)
	request_checkin.assert_not_called()
