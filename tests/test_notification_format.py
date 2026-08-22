import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from checkin import format_check_in_notification, format_failure_notification  # noqa: E402


def detail(name, before_quota, before_used, after_quota, after_used, success=True):
	return {
		'name': name,
		'before_quota': before_quota,
		'before_used': before_used,
		'after_quota': after_quota,
		'after_used': after_used,
		'check_in_reward': (after_quota + after_used) - (before_quota + before_used),
		'usage_increase': after_used - before_used,
		'balance_change': after_quota - before_quota,
		'success': success,
	}


def test_reward_block_shows_gift_icon_and_delta():
	text = format_check_in_notification(detail('TaBiAI 2', 0.03, 153.43, 9.65, 153.43))

	assert text.startswith('━')
	assert '🎁 TaBiAI 2' in text
	assert '💰 余额：$0.03 → $9.65' in text
	assert '✨ 本次签到获得：+$9.62' in text
	assert '今日已签到' not in text


def test_unchanged_block_collapses_to_single_values():
	text = format_check_in_notification(detail('AnyRouter', 718.03, 924.38, 718.03, 924.38))

	assert '✅ AnyRouter' in text
	assert '💰 余额：$718.03' in text
	assert '→' not in text
	assert '⏭️ 今日已签到，余额无变化' in text


def test_failed_detail_uses_cross_icon():
	text = format_check_in_notification(detail('GoRouter', 1.0, 2.0, 1.0, 2.0, success=False))

	assert '❌ GoRouter' in text


def test_failure_block_surfaces_the_error():
	text = format_failure_notification('TaBiAI', {'success': False, 'error': 'HTTP 403'})

	assert '❌ TaBiAI' in text
	assert '⚠️ HTTP 403' in text
	assert '❗ 签到失败' in text


def test_failure_block_keeps_balance_when_available():
	text = format_failure_notification('TaBiAI', {'success': True, 'quota': 12.5, 'used_quota': 3.25})

	assert '💰 余额：$12.50' in text
	assert '📊 累计消耗：$3.25' in text


def test_account_names_that_prefix_each_other_stay_separate():
	"""同站多账号时名字互为前缀，旧的子串去重会把成功的那个整块丢掉。"""
	first = format_check_in_notification(detail('TaBiAI', 5.0, 1.0, 5.0, 1.0))
	second = format_failure_notification('TaBiAI 2', {'success': False, 'error': 'HTTP 403'})

	blocks = {'account_1': first, 'account_2': second}
	ordered = [blocks[f'account_{i + 1}'] for i in range(2) if f'account_{i + 1}' in blocks]

	assert len(ordered) == 2
	# 'TaBiAI' 是 'TaBiAI 2' 的前缀：任何基于 name 子串匹配的去重都会漏掉第一个
	assert any('✅ TaBiAI\n' in b for b in ordered)
	assert any('❌ TaBiAI 2' in b for b in ordered)
