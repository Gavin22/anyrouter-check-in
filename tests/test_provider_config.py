import json

from utils.config import AppConfig, ProviderConfig


def test_builtin_provider_profile_persistence_defaults(monkeypatch):
	monkeypatch.delenv('PROVIDERS', raising=False)

	config = AppConfig.load_from_env()

	assert config.providers['anyrouter'].persist_profile is True
	assert config.providers['agentrouter'].persist_profile is False


def test_provider_profile_persistence_can_override_builtin(monkeypatch):
	monkeypatch.setenv(
		'PROVIDERS',
		json.dumps(
			{
				'anyrouter': {'domain': 'https://anyrouter.top', 'persist_profile': False},
				'agentrouter': {'domain': 'https://agentrouter.org', 'persist_profile': True},
			}
		),
	)

	config = AppConfig.load_from_env()

	assert config.providers['anyrouter'].persist_profile is False
	assert config.providers['agentrouter'].persist_profile is True


def test_custom_provider_profile_persistence_defaults_to_false(monkeypatch):
	monkeypatch.setenv('PROVIDERS', json.dumps({'custom': {'domain': 'https://custom.example.com'}}))

	config = AppConfig.load_from_env()

	assert config.providers['custom'].persist_profile is False


def test_provider_from_dict_inherits_profile_persistence_from_defaults():
	defaults = ProviderConfig(name='custom', domain='https://old.example.com', persist_profile=True)

	provider = ProviderConfig.from_dict(
		'custom',
		{'domain': 'https://new.example.com'},
		defaults=defaults,
	)

	assert provider.persist_profile is True


def test_existing_providers_keep_cookie_auth(monkeypatch):
	monkeypatch.delenv('PROVIDERS', raising=False)

	config = AppConfig.load_from_env()

	for name in ('anyrouter', 'agentrouter'):
		provider = config.providers[name]
		assert provider.uses_bearer_auth() is False
		assert provider.auth_scheme == 'cookie'
		assert provider.checkin_status_path is None


def test_builtin_bearer_providers(monkeypatch):
	monkeypatch.delenv('PROVIDERS', raising=False)

	config = AppConfig.load_from_env()

	expected_domains = {'gorouter': 'https://gorouter.app', 'tabitoken': 'https://tabitoken.com'}
	for name, domain in expected_domains.items():
		provider = config.providers[name]
		assert provider.domain == domain
		assert provider.uses_bearer_auth() is True
		assert provider.sign_in_path == '/api/user/checkin'
		assert provider.checkin_status_path == '/api/user/checkin'
		assert provider.needs_manual_check_in() is True
		assert provider.needs_waf_cookies() is False
		# 留空表示运行时从 /api/status 读取
		assert provider.turnstile_site_key == ''


def test_custom_provider_defaults_to_cookie_auth(monkeypatch):
	monkeypatch.setenv('PROVIDERS', json.dumps({'custom': {'domain': 'https://custom.example.com'}}))

	config = AppConfig.load_from_env()

	assert config.providers['custom'].uses_bearer_auth() is False


def test_bearer_provider_fields_can_be_overridden(monkeypatch):
	monkeypatch.setenv(
		'PROVIDERS',
		json.dumps(
			{
				'gorouter': {
					'domain': 'https://gorouter.app',
					'use_proxy': True,
					'turnstile_site_key': '0xTESTKEY',
				}
			}
		),
	)

	config = AppConfig.load_from_env()
	provider = config.providers['gorouter']

	assert provider.use_proxy is True
	assert provider.turnstile_site_key == '0xTESTKEY'
	# 未覆盖的字段应继承内置默认
	assert provider.uses_bearer_auth() is True
	assert provider.sign_in_path == '/api/user/checkin'
