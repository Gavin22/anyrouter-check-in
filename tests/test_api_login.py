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

