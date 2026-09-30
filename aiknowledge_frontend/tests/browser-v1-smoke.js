// Run with the Playwright browser_run_code_unsafe tool's filename argument.
// Uses synthetic API fixtures; this is not a live backend/model E2E test.
async (page) => {
  await page.unrouteAll({ behavior: 'wait' });
  page.setDefaultTimeout(10000);
  const base = 'http://127.0.0.1:18086';
  const spaceId = '22222222-2222-4222-8222-222222222222';
  const categoryId = '33333333-3333-4333-8333-333333333333';
  const linkId = '44444444-4444-4444-8444-444444444444';
  const timestamp = '2026-09-30T00:00:00Z';
  const space = { id: spaceId, name: 'V1验收空间', description: '合成验收数据', visibility: 'PUBLIC', guest_feedback_enabled: false, plan: 'FREE', created_at: timestamp, updated_at: timestamp };
  const category = { id: categoryId, space_id: spaceId, name: '公开资料', is_open: true, sort_order: 0, created_at: timestamp, updated_at: timestamp };
  const link = { id: linkId, space_id: spaceId, category_ids: [categoryId], status: 'ACTIVE', created_at: timestamp, revoked_at: null, expires_at: null };
  let failMutations = true;
  const sessionTokens = [];
  const errors = [];
  const onError = error => errors.push(error.message);
  page.on('pageerror', onError);
  await page.route('**/api/v1/**', async route => {
    const req = route.request();
    const pathname = new URL(req.url()).pathname;
    if (pathname.endsWith('/public/session')) {
      sessionTokens.push(req.postDataJSON().token);
      return route.fulfill({ json: { name: space.name, description: space.description, categories: [{name: category.name, description: '对外开放'}] } });
    }
    if (req.method() !== 'GET') {
      if (failMutations) return route.fulfill({ status: 503, json: { message: '验收模拟：服务暂不可用' } });
      if (pathname.endsWith('/share-links')) return route.fulfill({ json: { link, token: 'synthetic-share-token' } });
      return route.fulfill({ status: 204 });
    }
    let data = { items: [] };
    if (pathname.endsWith('/auth/me')) data = { id: '11111111-1111-4111-8111-111111111111', email: 'v1@example.test', display_name: '验收用户', status: 'ACTIVE' };
    if (pathname.endsWith('/spaces')) data = { items: [space] };
    if (pathname.endsWith('/categories')) data = { items: [category] };
    if (pathname.endsWith('/share-links')) data = { items: [link] };
    if (pathname.endsWith('/owner/conversations') || pathname.endsWith('/members')) data = [];
    if (pathname.endsWith('/usage')) data = { plan: 'FREE', documents_used: 0, members_used: 1, questions_used_today: 0, limits: { documents: 20, members: 1, questions_per_day: 100 } };
    if (pathname.endsWith('/public-analytics')) return route.fulfill({ status: 503, json: {message: '无统计夹具'} });
    await route.fulfill({ json: data });
  });
  const assert = (condition, message) => { if (!condition) throw new Error(message); };
  const result = { backend: 'synthetic API fixtures', checks: [] };
  try {
    await page.setViewportSize({width: 1440, height: 900});
    await page.goto(base);
    await page.getByText(space.name, {exact: true}).first().click();
    await page.getByText('公开设置', {exact: true}).click();
    await page.locator('.toggle').click();
    await page.getByText('验收模拟：服务暂不可用', {exact: true}).waitFor();
    assert(await page.locator('.toggle.is-on').count() === 1, 'Failed closure must retain the open state');
    result.checks.push('分类关闭失败：保持原状态并显示错误');
    await page.getByText('撤销链接', {exact: true}).click();
    await page.getByText('验收模拟：服务暂不可用', {exact: true}).waitFor();
    assert(await page.getByText('当前有效分享', {exact: true}).count() === 1, 'Failed revocation must retain the active link');
    result.checks.push('撤销链接失败：仍显示有效链接');
    await page.getByText('生成分享链接', {exact: true}).click();
    assert(await page.locator('.share-result').count() === 0, 'Failed share creation must not fabricate a token');
    result.checks.push('生成链接失败：不生成演示 token');
    failMutations = false;
    await page.getByText('生成分享链接', {exact: true}).click();
    await page.locator('.share-url').waitFor();
    const shareUrl = await page.locator('.share-url').innerText();
    assert(shareUrl === `${base}/#/pages/public/public?token=synthetic-share-token`, 'Incorrect copied public route');
    assert((await page.locator('.embed-snippet-code').innerText()).includes(`publicUrl: "${base}"`), 'Embed snippet is missing publicUrl');
    result.checks.push('分享成功：正确 hash 路由与完整嵌入配置');
    await page.goto(shareUrl);
    await page.getByText(space.name, {exact: true}).first().waitFor();
    assert(sessionTokens.includes('synthetic-share-token'), 'Share URL did not initialize the public session');
    result.checks.push('分享链接直达公开页面并建立访客会话');
    for (const width of [390, 375]) {
      await page.setViewportSize({width, height: 844});
      const sizes = await page.evaluate(() => ({viewport: document.documentElement.clientWidth, content: document.documentElement.scrollWidth}));
      assert(sizes.content <= sizes.viewport + 1, `Public page overflows at ${width}px`);
      result.checks.push(`公开页 ${width}px：无页面横向溢出`);
    }
    assert(errors.length === 0, `Browser errors: ${errors.join('; ')}`);
    result.pageErrors = errors;
    return result;
  } finally {
    page.off('pageerror', onError);
    await page.unrouteAll({behavior: 'wait'});
  }
}
