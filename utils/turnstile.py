"""Turnstile token 获取：用浏览器渲染 Cloudflare Turnstile 组件并取回 token。

NewAPI 的签到接口挂了 middleware.TurnstileCheck()：服务端从 query 参数
`turnstile` 取 token 后去 Cloudflare siteverify 校验，纯 HTTP 请求无法完成签到。
好在 token 只绑定「域名 + 公开 site key」、不绑定登录态，所以这里只负责取 token，
签到请求仍由 httpx 带访问令牌发出。

实测要点（gorouter.app / tabitoken.com，2026-08）：
- 站点首页是 SPA 且自己会加载 api.js，在其上二次 render 组件永远出不来 iframe，
  因此这里用 route 拦截伪造一个同源空白页，避免和站点脚本互相干扰。
- 组件渲染的是 managed 交互式挑战（"请验证您是真人" 复选框），不会自动过，
  必须点一下复选框；点组件正中间无效，复选框在左侧约 20px 处。
- 组件 iframe 在 closed shadow root 里，Playwright 的 CSS 选择器穿不进去
  （`#holder iframe` 匹配不到），所以只能按坐标点。
- token 单次有效、约 300 秒过期，且要与后续签到请求同出口 IP。
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from utils.browser import launch_login_context, load_browser_login_settings, prepare_browser_page, save_login_screenshot
from utils.debug import debug_print

if TYPE_CHECKING:
	from playwright.async_api import Page

TURNSTILE_SCRIPT_URL = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit'
PROBE_PATH = '/__checkin_turnstile'
PROBE_HTML = (
	'<!doctype html><html><head><meta charset="utf-8"><title>checkin</title></head>'
	'<body style="margin:0;padding:24px"><div id="ts_holder"></div></body></html>'
)
HOLDER_SELECTOR = '#ts_holder'
SCRIPT_READY_TIMEOUT_MS = 30_000
WIDGET_RENDER_TIMEOUT_MS = 20_000
# 整个挑战的时间预算。组件先显示「正在验证...」转圈，大约 10 秒后才落到
# 「请验证您是真人」复选框，转圈期间点击完全无效，所以要边等边反复点。
INTERACTIVE_TOTAL_WAIT_MS = 90_000
# 首次点击前留出的时间：机房 IP 偶尔会直接自动放行，不必上来就点
FIRST_CLICK_DELAY_MS = 6_000
# 两次点击的最小间隔。点中之后 Cloudflare 要 1~3 秒出结果，间隔太短
# 会把正在验证的挑战打回未验证状态。
CLICK_INTERVAL_MS = 8_000
POLL_INTERVAL_MS = 400
# 复选框相对组件左上角的偏移：normal 尺寸 300x65，compact 尺寸 150x140
CHECKBOX_OFFSETS = ((20, 32), (28, 41), (20, 102))

_RENDER_JS = """(siteKey) => {
	if (!window.turnstile) return null;
	const state = { token: null, failed: false };
	window.__checkinTurnstile = state;
	try {
		state.widgetId = window.turnstile.render('#ts_holder', {
			sitekey: siteKey,
			callback: (token) => {
				state.token = token;
			},
			'error-callback': () => {
				state.failed = true;
			},
			'timeout-callback': () => {
				state.failed = true;
			},
		});
	} catch (err) {
		state.failed = true;
		state.error = String(err);
	}
	return state.widgetId ?? null;
}"""

_READ_STATE_JS = """() => {
	const state = window.__checkinTurnstile;
	if (!state) return { token: null, failed: true };
	return { token: state.token || null, failed: !!state.failed };
}"""

_WIDGET_SIZED_JS = """() => {
	const holder = document.querySelector('#ts_holder');
	if (!holder) return false;
	const rect = holder.getBoundingClientRect();
	return rect.width > 50 && rect.height > 30;
}"""


async def _human_click(page: Page, x: float, y: float) -> None:
	"""带移动轨迹和停顿的点击。

	`page.mouse.click()` 会把 move/down/up 挤在同一瞬间、且没有前置移动，
	Turnstile 会当成机器人点击直接忽略——实测这样点复选框毫无反应，而分成
	移动、停顿、按下、抬起就能立刻过。cloakbrowser 的 humanize 只作用于
	locator 操作，这里用的是裸 mouse API，所以得自己补上。
	"""
	await page.mouse.move(x - 120, y - 60)
	await asyncio.sleep(0.12)
	await page.mouse.move(x, y, steps=14)
	await asyncio.sleep(0.18)
	await page.mouse.down()
	await asyncio.sleep(0.09)
	await page.mouse.up()


async def _await_token(page: Page, account_name: str) -> str | None:
	"""边等 token 边周期性点击复选框，直到拿到 token 或用完时间预算。

	组件的生命周期是「正在验证...」转圈约 10 秒，再落到「请验证您是真人」复选框。
	转圈期间的点击是彻底的空操作，所以无法先等一个状态再点一次——只能按固定
	间隔重复点，转圈时白点、复选框出现后那一下就会生效。

	组件 iframe 在 closed shadow root 里，选择器和 frame_locator 都进不去
	（`#ts_holder iframe` 匹配不到），只能按坐标点；点组件正中间也无效。
	"""
	interval = POLL_INTERVAL_MS / 1000
	deadline = INTERACTIVE_TOTAL_WAIT_MS / 1000
	first_click_at = FIRST_CLICK_DELAY_MS / 1000
	click_gap = CLICK_INTERVAL_MS / 1000

	waited = 0.0
	last_click: float | None = None
	clicks = 0

	while waited < deadline:
		state = await page.evaluate(_READ_STATE_JS)
		if state.get('token'):
			if clicks:
				debug_print(f'[INFO] {account_name}: Turnstile solved after {clicks} click(s), {waited:.1f}s')
			return state['token']
		if state.get('failed'):
			debug_print(f'[INFO] {account_name}: Turnstile reported failure after {waited:.1f}s')
			return None

		due = waited >= first_click_at and (last_click is None or waited - last_click >= click_gap)
		if due:
			offset_x, offset_y = CHECKBOX_OFFSETS[clicks % len(CHECKBOX_OFFSETS)]
			box = None
			try:
				box = await page.locator(HOLDER_SELECTOR).bounding_box()
			except Exception as exc:  # nosec B110
				debug_print(f'[INFO] {account_name}: Turnstile holder has no bounding box: {exc}')

			if box and offset_y <= box['height'] + 10 and offset_x <= box['width'] + 10:
				try:
					await _human_click(page, box['x'] + offset_x, box['y'] + offset_y)
					clicks += 1
					last_click = waited
					debug_print(
						f'[INFO] {account_name}: Turnstile click #{clicks} at +{offset_x},+{offset_y} ({waited:.1f}s)'
					)
				except Exception as exc:  # nosec B110
					debug_print(f'[INFO] {account_name}: Turnstile click failed: {exc}')
					last_click = waited
			else:
				last_click = waited

		await asyncio.sleep(interval)
		waited += interval

	debug_print(f'[INFO] {account_name}: Turnstile gave up after {clicks} click(s), {waited:.1f}s')
	return None


async def mint_turnstile_token(
	domain: str,
	site_key: str,
	*,
	account_name: str,
	provider_name: str,
	use_proxy: bool = False,
) -> str | None:
	"""在站点同源的空白页上渲染 Turnstile 组件，返回可用于签到接口的 token。

	token 单次有效、约 300 秒过期，取到后应立即发起签到请求；且必须与签到请求
	走同一个出口，否则 siteverify 可能拒绝。
	"""
	if not site_key:
		print(f'[FAILED] {account_name}: Turnstile site key is empty, cannot mint token')
		return None

	print(f'[PROCESSING] {account_name}: Starting browser to mint Turnstile token...')

	# 必须与邮箱密码登录复用同一套启动参数：同进程内先启动 headless 且未开启
	# humanize 的浏览器，会让后续 humanize 浏览器的点击无法真正派发到页面。
	settings = load_browser_login_settings(account_name, provider_name, persist_profile=False)
	debug_print(f'[INFO] {account_name}: Turnstile browser headless={settings.headless}, humanize={settings.humanize}')

	try:
		context = await launch_login_context(settings, use_proxy=use_proxy)
	except Exception as exc:
		print(f'[FAILED] {account_name}: Browser launch failed: {exc}')
		return None

	page = None
	try:
		page = await context.new_page()
		# Turnstile 不会在隐藏页面上处理挑战：页面在后台时点击复选框没有任何反应，
		# 表现为「同样的坐标在一个站点能过、另一个站点点不动」。
		try:
			await page.bring_to_front()
		except Exception as exc:  # nosec B110
			debug_print(f'[INFO] {account_name}: bring_to_front skipped: {exc}')
		await prepare_browser_page(page)

		# 伪造一个同源空白页：站点首页的 SPA 自己会加载 api.js，在其上二次
		# render 组件出不来 iframe，必须换到干净文档里。
		await page.route(
			f'**{PROBE_PATH}',
			lambda route: route.fulfill(status=200, content_type='text/html; charset=utf-8', body=PROBE_HTML),
		)
		await page.goto(f'{domain}{PROBE_PATH}', wait_until='domcontentloaded', timeout=settings.wait_timeout_ms)

		await page.add_script_tag(url=TURNSTILE_SCRIPT_URL)
		await page.wait_for_function('() => !!window.turnstile', timeout=SCRIPT_READY_TIMEOUT_MS)

		widget_id = await page.evaluate(_RENDER_JS, site_key)
		if widget_id is None:
			print(f'[FAILED] {account_name}: Turnstile widget failed to render')
			await save_login_screenshot(page, provider_name, account_name, 'turnstile-render-failed')
			return None

		try:
			await page.wait_for_function(_WIDGET_SIZED_JS, timeout=WIDGET_RENDER_TIMEOUT_MS)
		except Exception as exc:
			debug_print(f'[INFO] {account_name}: Turnstile widget never got a size: {exc}')

		token = await _await_token(page, account_name)

		if not token:
			print(f'[FAILED] {account_name}: Could not obtain Turnstile token')
			await save_login_screenshot(page, provider_name, account_name, 'turnstile-no-token')
			return None

		print(f'[SUCCESS] {account_name}: Got Turnstile token ({len(token)} chars)')
		return token

	except Exception as exc:
		print(f'[FAILED] {account_name}: Error while minting Turnstile token: {exc}')
		if page is not None:
			await save_login_screenshot(page, provider_name, account_name, 'turnstile-error')
		return None
	finally:
		await context.close()
