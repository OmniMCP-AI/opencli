import { AuthRequiredError, CommandExecutionError } from '@jackwener/opencli/errors';
import { registerSiteAuthCommands } from '../_shared/site-auth.js';

const BASE_URL = 'https://sso.geiwohuo.com';
const LOGIN_URL = `${BASE_URL}/#/login`;
const AFTERSALES_LIST_URL = `${BASE_URL}/#/gsp/order-management/after-sales-list`;
const LIST_API = `${BASE_URL}/gsp/aftersalesOrder/list`;
const DEFAULT_BUILD_VERSION = '2026-07-07 17:45';
const DEFAULT_VISITOR_ID = '_n-OBFckyOByISQY_GJV5';

function parseCookieValue(cookie, name) {
  const match = String(cookie || '').match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : '';
}

function buildVerifyScript() {
  return `
    (async () => {
      const response = await fetch(${JSON.stringify(LIST_API)}, {
        method: 'POST',
        credentials: 'include',
        headers: {
          accept: '*/*',
          'accept-language': 'zh-CN,zh;q=0.9',
          'build-version': ${JSON.stringify(DEFAULT_BUILD_VERSION)},
          'content-type': 'application/json;Charset=utf-8',
          'origin-path': '/order-management/after-sales-list',
          'origin-url': ${JSON.stringify(AFTERSALES_LIST_URL)},
          'x-log-visitorid': ${JSON.stringify(DEFAULT_VISITOR_ID)},
        },
        body: JSON.stringify({ quickType: 0, page: 1, perPage: 1 }),
      });
      const text = await response.text();
      let body = null;
      try { body = JSON.parse(text); } catch {}
      return {
        status: response.status,
        url: response.url,
        body,
        textPreview: text.slice(0, 180),
        href: location.href,
        title: document.title || '',
        cookie: document.cookie || '',
      };
    })()
  `;
}

async function verifySheinIdentity(page) {
  const probe = await page.evaluate(buildVerifyScript());
  const code = probe?.body?.code != null ? String(probe.body.code) : '';
  if (probe?.status === 302 || code === '20302' || /登录|login/i.test(String(probe?.textPreview || ''))) {
    throw new AuthRequiredError('sso.geiwohuo.com', `SHEIN GSP session is not ready${code ? ` (code=${code})` : ''}`);
  }
  if (code && code !== '0') {
    throw new CommandExecutionError(`SHEIN auth probe failed: code=${code} msg=${probe?.body?.msg || ''}`);
  }
  if (!probe?.body || code !== '0') {
    throw new CommandExecutionError(`SHEIN auth probe returned an unreadable response: ${probe?.textPreview || ''}`);
  }

  const cookie = String(probe.cookie || '');
  const data = Array.isArray(probe.body?.info?.data) ? probe.body.info.data : [];
  const first = data.find(item => item && typeof item === 'object') || {};
  return {
    site_id: parseCookieValue(cookie, 'SITE_ID'),
    store_site: parseCookieValue(cookie, 'gsp_store_site') || first.site || '',
    page_title: probe.title || '',
  };
}

async function pollSheinIdentity(page) {
  return verifySheinIdentity(page);
}

registerSiteAuthCommands({
  site: 'shein',
  domain: 'sso.geiwohuo.com',
  loginUrl: LOGIN_URL,
  columns: ['store_site', 'site_id', 'page_title'],
  loginDescription: 'Open SHEIN seller login and wait until the GSP session is ready',
  whoamiDescription: 'Check whether the SHEIN seller GSP session is ready',
  verify: verifySheinIdentity,
  poll: pollSheinIdentity,
});

export const __test__ = {
  buildVerifyScript,
  parseCookieValue,
};
