import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from checkin import (  # noqa: E402
	SEPARATOR,
	add_list_index,
	beijing_now_text,
	format_check_in_notification,
	format_failure_notification,
)


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


def test_list_index_is_prefixed_to_the_account_line():
	numbered = add_list_index(format_check_in_notification(detail('GoRouter', 0.12, 1.0, 7.70, 1.0)), 3)

	lines = numbered.split('\n')
	assert lines[0].startswith('━')  # 分隔线仍在最前
	assert lines[1] == '3. 🎁 GoRouter'
	assert '💰 余额：$0.12 → $7.70' in numbered


def test_list_index_works_for_failure_and_exception_blocks():
	failure = add_list_index(format_failure_notification('TaBiAI', {'success': False, 'error': 'HTTP 403'}), 1)
	# 运行异常的块在 main() 里手拼，结构和另外两种一致
	crash = add_list_index(f'{SEPARATOR}\n❌ TaBiAI 2\n   ⚠️ 运行异常：boom', 2)

	assert failure.split('\n')[1] == '1. ❌ TaBiAI'
	assert crash.split('\n')[1] == '2. ❌ TaBiAI 2'


def test_list_index_stays_sequential_when_only_some_accounts_notify():
	"""余额没变、只有个别账号失败时通知里只有子集，序号要连续，不能跟着 account_key 留空号。"""
	blocks = {'account_2': format_failure_notification('A', None), 'account_5': format_failure_notification('B', None)}
	ordered = [blocks[f'account_{i + 1}'] for i in range(7) if f'account_{i + 1}' in blocks]
	numbered = [add_list_index(block, position) for position, block in enumerate(ordered, start=1)]

	assert [n.split('\n')[1] for n in numbered] == ['1. ❌ A', '2. ❌ B']


def test_notification_time_is_beijing_time():
	"""CI runner 是 UTC，通知时间必须是 UTC+8，否则显示的时间比国内早 8 小时。"""
	rendered = datetime.strptime(beijing_now_text(), '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone(timedelta(hours=8)))

	# 和 UTC 当前时刻比，这样本机时区是不是 UTC+8 都不影响结论
	assert abs((rendered - datetime.now(timezone.utc)).total_seconds()) < 5
