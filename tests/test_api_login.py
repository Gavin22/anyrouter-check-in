from unittest.mock import ANY, AsyncMock, MagicMock

import pytest

import checkin
from utils.config import ProviderConfig


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
async def test_login_with_api_credentials_bootstraps_waf_cookies(monkeypatch):
	response = MagicMock()
	response.status_code = 200
	response.json.return_value = {'success': True, 'data': {'id': 47933}}

	client = MagicMock()
	client.cookies = {}

	async def post(*args, **kwargs):
		client.cookies['session'] = 'fresh-session'
		return response

	client.post = AsyncMock(side_effect=post)
	client.__aenter__ = AsyncMock(return_value=client)
	client.__aexit__ = AsyncMock(return_value=None)
	monkeypatch.setattr(checkin.httpx, 'AsyncClient', lambda **kwargs: client)
	waf_login = AsyncMock(return_value={'acw_tc': 'waf-cookie', 'acw_sc__v2': 'challenge-cookie'})
	monkeypatch.setattr(checkin, 'get_waf_cookies_with_browser', waf_login)

	provider = ProviderConfig(
		name='agentrouter',
		domain='https://ps.air-outer.com',
		login_path='/login',
		login_api_path='/api/user/login',
		sign_in_path=None,
		bypass_method='waf_cookies',
		waf_cookie_names=['acw_tc'],
	)
	result = await checkin.login_with_api_credentials('Agent Router', provider, 'user@example.com', 'secret')

	assert result is not None
	assert result.cookies == {
		'acw_tc': 'waf-cookie',
		'acw_sc__v2': 'challenge-cookie',
		'session': 'fresh-session',
	}
	waf_login.assert_awaited_once_with(
		'Agent Router',
		'https://ps.air-outer.com/login',
		['acw_tc'],
		use_proxy=False,
	)
