import { CommandExecutionError } from '@jackwener/opencli/errors';
import { cli, Strategy } from '@jackwener/opencli/registry';

const BASE_URL = 'https://sso.geiwohuo.com';
const DAILY_TRAFFIC_PAGE_URL = `${BASE_URL}/#/sbn/merchandise/details`;
const DAILY_TRAFFIC_API = `${BASE_URL}/sbn/new_goods/get_skc_diagnose_list`;
const DAILY_TRAFFIC_API_PATTERN = '/sbn/new_goods/get_skc_diagnose_list';

export const SHEIN_DAILY_TRAFFIC_COLUMNS = [
    'date',
    'queried_start_date',
    'queried_end_date',
    'total_count',
    'page_num',
    'request_url',
    'goods_name',
    'img_url',
    'spu',
    'skc',
    'sku_supplier_no',
    'new_goods_tag',
    'layer_name',
    'onsale_flag',
    'sale_flag',
    'multicolor_flag',
    'goods_uv_idx',
    'eps_uv_idx',
    'bounce_uv_idx',
    'bounce_rate',
    'search_click_cnt',
    'like_cnt',
    'cart_uv_idx',
    'cart_pv_idx',
    'gds_cart_ctr_idx',
    'pay_uv_idx',
    'pay_order_cnt',
    'gmv',
    'gds_pay_ctr_idx',
    'sale_uv_idx',
    'sale_cnt',
    'sale_gmv',
    'gds_sale_ctr_idx',
    'confirm_ctr_idx',
    'total_quality_level',
    'total_comment_cnt',
    'bad_comment_cnt',
    'bad_comment_rate',
    'return_order_cnt',
    'return_qty',
    'new_cate_1_name',
    'new_cate_2_name',
    'new_cate_3_name',
    'new_cate_4_name',
    'brand',
    'list_name',
    'list_type',
    'list_rank',
    'prom_tag',
    'prom_names',
    'prom_ids',
    'prom_inf_ing_json',
    'right_campaign_json',
    'raw_json',
];

function asObject(value) {
    return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}

function asArray(value) {
    return Array.isArray(value) ? value : [];
}

function asRecordArray(value) {
    return asArray(value).filter((item) => item && typeof item === 'object' && !Array.isArray(item));
}

function stringValue(value) {
    if (value === null || value === undefined) return '';
    return typeof value === 'string' ? value : String(value);
}

function numberOrNull(value) {
    if (typeof value === 'number' && Number.isFinite(value)) return value;
    if (typeof value === 'string' && value.trim() !== '') {
        const parsed = Number(value);
        if (Number.isFinite(parsed)) return parsed;
    }
    return null;
}

function normalizeUrl(raw) {
    const value = stringValue(raw).trim();
    if (!value) return '';
    if (value.startsWith('//')) return `https:${value}`;
    return value;
}

function unwrapEvaluateResult(payload) {
    if (payload && typeof payload === 'object' && !Array.isArray(payload) && 'session' in payload && 'data' in payload) {
        return payload.data;
    }
    return payload;
}

function lowerCaseKeys(record) {
    const source = asObject(record);
    const lowered = {};
    for (const [key, value] of Object.entries(source)) {
        lowered[String(key).toLowerCase()] = stringValue(value);
    }
    return lowered;
}

function parseJsonText(raw, label) {
    const text = stringValue(raw).trim();
    if (!text) throw new CommandExecutionError(`Missing ${label}`);
    try {
        return JSON.parse(text);
    } catch (error) {
        throw new CommandExecutionError(`Malformed ${label}: ${error?.message || error}`);
    }
}

function ensureSuccessfulApiPayload(payload, label) {
    if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
        throw new CommandExecutionError(`Malformed ${label}`);
    }
    if (payload.code !== undefined && String(payload.code) !== '0') {
        throw new CommandExecutionError(`SHEIN ${label} failed: code=${String(payload.code)} msg=${stringValue(payload.msg)}`);
    }
    return payload;
}

function parsePositiveInt(raw, label, fallback) {
    if (raw === undefined || raw === null || raw === '') return fallback;
    const parsed = Number(raw);
    if (!Number.isInteger(parsed) || parsed <= 0) {
        throw new CommandExecutionError(`${label} must be a positive integer. Received: "${String(raw)}"`);
    }
    return parsed;
}

function parseNonNegativeInt(raw, label, fallback) {
    if (raw === undefined || raw === null || raw === '') return fallback;
    const parsed = Number(raw);
    if (!Number.isInteger(parsed) || parsed < 0) {
        throw new CommandExecutionError(`${label} must be a non-negative integer. Received: "${String(raw)}"`);
    }
    return parsed;
}

function dateFromParts(year, month, day) {
    return new Date(Date.UTC(Number(year), Number(month) - 1, Number(day)));
}

function formatIsoDate(date) {
    return date.toISOString().slice(0, 10);
}

function yyyymmdd(isoDate) {
    return isoDate.replaceAll('-', '');
}

function normalizeDateInput(raw, label = 'date') {
    const text = stringValue(raw).trim();
    if (!text) return '';
    const compact = text.match(/^(\d{4})(\d{2})(\d{2})$/);
    const dashed = text.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
    const match = compact || dashed;
    if (!match) {
        throw new CommandExecutionError(`${label} must be YYYY-MM-DD or YYYYMMDD. Received: "${text}"`);
    }
    const [, year, month, day] = match;
    const date = dateFromParts(year, month, day);
    if (
        date.getUTCFullYear() !== Number(year)
        || date.getUTCMonth() !== Number(month) - 1
        || date.getUTCDate() !== Number(day)
    ) {
        throw new CommandExecutionError(`${label} is not a valid date. Received: "${text}"`);
    }
    return formatIsoDate(date);
}

function defaultYesterday(now = new Date()) {
    const date = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    date.setDate(date.getDate() - 1);
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
}

function resolveDateRange(kwargs = {}, now = new Date()) {
    let start = normalizeDateInput(kwargs.startDate, '--startDate');
    let end = normalizeDateInput(kwargs.endDate, '--endDate');
    if (!start && !end) start = end = defaultYesterday(now);
    else if (start && !end) end = start;
    else if (!start && end) start = end;
    if (start > end) [start, end] = [end, start];

    const dates = [];
    const cursor = dateFromParts(start.slice(0, 4), start.slice(5, 7), start.slice(8, 10));
    const stop = dateFromParts(end.slice(0, 4), end.slice(5, 7), end.slice(8, 10));
    while (cursor <= stop) {
        dates.push(formatIsoDate(cursor));
        cursor.setUTCDate(cursor.getUTCDate() + 1);
    }
    return dates;
}

function normalizeCountrySite(rawCliValue, capturedValue) {
    if (rawCliValue !== undefined && rawCliValue !== null && stringValue(rawCliValue).trim() !== '') {
        const values = stringValue(rawCliValue).split(',').map((item) => item.trim()).filter(Boolean);
        return values.length > 0 ? values : ['shein-all'];
    }
    if (Array.isArray(capturedValue)) {
        const values = capturedValue.map(stringValue).map((item) => item.trim()).filter(Boolean);
        return values.length > 0 ? values : ['shein-all'];
    }
    const captured = stringValue(capturedValue).trim();
    return captured ? [captured] : ['shein-all'];
}

function filterReplayableHeaders(headers) {
    const lowered = lowerCaseKeys(headers);
    const replayable = {};
    const blocked = new Set([
        'accept-encoding',
        'connection',
        'content-length',
        'cookie',
        'host',
        'origin',
        'referer',
    ]);
    for (const [name, value] of Object.entries(lowered)) {
        if (blocked.has(name) || name.startsWith('sec-')) continue;
        replayable[name] = value;
    }
    return replayable;
}

function urlMatchesApi(rawUrl, apiUrl) {
    const value = stringValue(rawUrl);
    if (!value) return false;
    if (value.includes(apiUrl)) return true;
    try {
        return value.includes(new URL(apiUrl).pathname);
    } catch {
        return false;
    }
}

function extractTrafficCaptureContext(entries) {
    const match = [...asArray(entries)].reverse().find((entry) => {
        const row = asObject(entry);
        return urlMatchesApi(row.url, DAILY_TRAFFIC_API)
            && stringValue(row.responsePreview).trim()
            && numberOrNull(row.responseStatus) !== null
            && numberOrNull(row.responseStatus) < 400;
    });
    if (!match) {
        throw new CommandExecutionError('Failed to capture SHEIN daily traffic first-page request');
    }
    const requestBody = asObject(parseJsonText(match.requestBodyPreview, 'SHEIN daily traffic request body'));
    const response = ensureSuccessfulApiPayload(
        parseJsonText(match.responsePreview, 'SHEIN daily traffic response'),
        'daily traffic response',
    );
    return {
        headers: filterReplayableHeaders(match.requestHeaders),
        body: requestBody,
        response,
        requestUrl: stringValue(match.url) || DAILY_TRAFFIC_API,
    };
}

function buildDailyTrafficBody(firstPageBody, pageNum, date, options = {}) {
    const captured = asObject(firstPageBody);
    const pageSize = parsePositiveInt(
        options.pageSize === undefined || options.pageSize === null || options.pageSize === '' ? captured.pageSize : options.pageSize,
        '--pageSize',
        100,
    );
    return {
        ...captured,
        areaCd: stringValue(options.areaCd).trim() || stringValue(captured.areaCd).trim() || 'cn',
        countrySite: normalizeCountrySite(options.countrySite, captured.countrySite),
        dt: yyyymmdd(date),
        startDate: yyyymmdd(date),
        endDate: yyyymmdd(date),
        pageNum,
        pageSize,
    };
}

function getInfo(payload) {
    return asObject(payload?.info ?? payload?.payload?.info);
}

function getRows(payload) {
    return asRecordArray(getInfo(payload).data);
}

function getTotalCount(infoOrPayload, fallbackRows = 0) {
    const source = asObject(infoOrPayload?.info ? infoOrPayload.info : infoOrPayload);
    for (const key of ['total', 'totalCount', 'count']) {
        const parsed = numberOrNull(source[key]);
        if (parsed !== null) return parsed;
    }
    const meta = asObject(source.meta);
    for (const key of ['total', 'totalCount', 'count']) {
        const parsed = numberOrNull(meta[key]);
        if (parsed !== null) return parsed;
    }
    return fallbackRows;
}

function scalar(value) {
    if (value === null || value === undefined) return '';
    if (typeof value === 'object') return '';
    return value;
}

function campaignRows(row) {
    return asRecordArray(asObject(row.promCampaign).promInfIng);
}

function rightCampaignRows(row) {
    const promCampaign = asObject(row.promCampaign);
    return asArray(row.rightCampaign).length > 0 ? asArray(row.rightCampaign) : asArray(promCampaign.rightCampaign);
}

function joinCampaignField(row, field) {
    return campaignRows(row).map((item) => stringValue(item[field]).trim()).filter(Boolean).join(' | ');
}

function flattenDailyTrafficRow(rawRow, meta) {
    const row = asObject(rawRow);
    const date = normalizeDateInput(meta.date, 'daily traffic row date');
    const promCampaign = asObject(row.promCampaign);
    return {
        date,
        queried_start_date: yyyymmdd(date),
        queried_end_date: yyyymmdd(date),
        total_count: meta.totalCount ?? '',
        page_num: meta.pageNum ?? '',
        request_url: stringValue(meta.requestUrl),
        goods_name: scalar(row.goodsName),
        img_url: normalizeUrl(row.imgUrl || row.imageUrl),
        spu: scalar(row.spu),
        skc: scalar(row.skc),
        sku_supplier_no: scalar(row.skuSupplierNo),
        new_goods_tag: scalar(row.newGoodsTag),
        layer_name: scalar(row.layerNm),
        onsale_flag: scalar(row.onsaleFlag),
        sale_flag: scalar(row.saleFlag),
        multicolor_flag: scalar(row.multicolorFlag),
        goods_uv_idx: scalar(row.goodsUvIdx),
        eps_uv_idx: scalar(row.epsUvIdx),
        bounce_uv_idx: scalar(row.bounceUvIdx),
        bounce_rate: scalar(row.bounceRate),
        search_click_cnt: scalar(row.searchClickCnt),
        like_cnt: scalar(row.likeCnt),
        cart_uv_idx: scalar(row.cartUvIdx),
        cart_pv_idx: scalar(row.cartPvIdx),
        gds_cart_ctr_idx: scalar(row.gdsCartCtrIdx),
        pay_uv_idx: scalar(row.payUvIdx),
        pay_order_cnt: scalar(row.payOrderCnt),
        gmv: scalar(row.gmv),
        gds_pay_ctr_idx: scalar(row.gdsPayCtrIdx),
        sale_uv_idx: scalar(row.saleUvIdx),
        sale_cnt: scalar(row.saleCnt),
        sale_gmv: scalar(row.saleGmv),
        gds_sale_ctr_idx: scalar(row.gdsSaleCtrIdx),
        confirm_ctr_idx: scalar(row.confirmCtrIdx),
        total_quality_level: scalar(row.totalQualityLevel),
        total_comment_cnt: scalar(row.totalCommentCnt),
        bad_comment_cnt: scalar(row.payBadCommentCnt ?? row.badCommentCnt),
        bad_comment_rate: scalar(row.badCommentRate),
        return_order_cnt: scalar(row.returnOrderCnt),
        return_qty: scalar(row.returnQty),
        new_cate_1_name: scalar(row.newCate1Nm),
        new_cate_2_name: scalar(row.newCate2Nm),
        new_cate_3_name: scalar(row.newCate3Nm),
        new_cate_4_name: scalar(row.newCate4Nm),
        brand: scalar(row.brand),
        list_name: scalar(row.listName),
        list_type: scalar(row.listType),
        list_rank: scalar(row.listRank),
        prom_tag: scalar(promCampaign.promTag),
        prom_names: joinCampaignField(row, 'promNm'),
        prom_ids: joinCampaignField(row, 'promId'),
        prom_inf_ing_json: campaignRows(row),
        right_campaign_json: rightCampaignRows(row),
        raw_json: row,
    };
}

function buildTapCaptureJs({ pattern, timeoutMs, targetUrl, clickSearch = false, reloadIfSameUrl = false }) {
    return `
      (async () => {
        const pattern = ${JSON.stringify(pattern)};
        const timeoutMs = ${JSON.stringify(timeoutMs)};
        const targetUrl = ${JSON.stringify(targetUrl || '')};
        const clickSearch = ${clickSearch ? 'true' : 'false'};
        const reloadIfSameUrl = ${reloadIfSameUrl ? 'true' : 'false'};
        const captures = [];
        const errors = [];
        let finished = false;
        let resolveCapture;
        const capturePromise = new Promise((resolve) => { resolveCapture = resolve; });

        const visible = (el) => {
          if (!(el instanceof HTMLElement)) return false;
          const style = window.getComputedStyle(el);
          if (style.display === 'none' || style.visibility === 'hidden' || style.pointerEvents === 'none') return false;
          const rect = el.getBoundingClientRect();
          return rect.width > 0 && rect.height > 0;
        };
        const textOf = (el) => (el?.textContent || '').replace(/\\s+/g, ' ').trim();
        const pushCapture = (payload) => {
          captures.push(payload);
          if (!finished) {
            finished = true;
            resolveCapture(true);
          }
        };
        const readHeaders = (value) => {
          try {
            if (!value) return {};
            if (value instanceof Headers) return Object.fromEntries(value.entries());
            if (Array.isArray(value)) return Object.fromEntries(value.map(([k, v]) => [String(k), String(v)]));
            if (typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([k, v]) => [String(k), String(v)]));
          } catch {}
          return {};
        };
        const readBody = async (body, request) => {
          try {
            if (body == null) return '';
            if (typeof body === 'string') return body;
            if (typeof URLSearchParams !== 'undefined' && body instanceof URLSearchParams) return body.toString();
            if (typeof FormData !== 'undefined' && body instanceof FormData) return '[formdata]';
            if (typeof Blob !== 'undefined' && body instanceof Blob) return '[blob]';
            if (typeof ArrayBuffer !== 'undefined' && body instanceof ArrayBuffer) return '[arraybuffer]';
            return String(body);
          } catch {}
          try {
            if (request) return await request.clone().text();
          } catch {}
          return '';
        };

        const origFetch = window.fetch;
        const xhrProto = XMLHttpRequest.prototype;
        const origOpen = xhrProto.open;
        const origSend = xhrProto.send;
        const origSetRequestHeader = xhrProto.setRequestHeader;

        window.fetch = async function (...args) {
          const request = args[0] instanceof Request ? args[0] : null;
          const init = args[1] || {};
          const reqUrl = request ? request.url : String(args[0] || '');
          const reqMethod = String(init.method || request?.method || 'GET').toUpperCase();
          const reqHeaders = readHeaders(init.headers || request?.headers);
          const reqBody = await readBody(init.body, request);
          const response = await origFetch.apply(this, args);
          if (pattern && reqUrl.includes(pattern)) {
            try {
              const text = await response.clone().text();
              pushCapture({
                kind: 'fetch',
                url: reqUrl,
                method: reqMethod,
                requestHeaders: reqHeaders,
                requestBodyPreview: reqBody,
                responseStatus: response.status,
                responsePreview: text,
                timestamp: Date.now(),
              });
            } catch (error) {
              errors.push({ kind: 'fetch', url: reqUrl, error: String(error) });
            }
          }
          return response;
        };

        xhrProto.open = function (method, url) {
          this.__opencliSheinTrafficUrl = String(url || '');
          this.__opencliSheinTrafficMethod = String(method || 'GET').toUpperCase();
          this.__opencliSheinTrafficHeaders = {};
          return origOpen.apply(this, arguments);
        };
        xhrProto.setRequestHeader = function (name, value) {
          try {
            const headers = this.__opencliSheinTrafficHeaders || {};
            headers[String(name)] = String(value);
            this.__opencliSheinTrafficHeaders = headers;
          } catch {}
          return origSetRequestHeader.apply(this, arguments);
        };
        xhrProto.send = function (body) {
          const reqUrl = String(this.__opencliSheinTrafficUrl || '');
          if (pattern && reqUrl.includes(pattern)) {
            const reqMethod = String(this.__opencliSheinTrafficMethod || 'GET');
            const reqHeaders = this.__opencliSheinTrafficHeaders || {};
            const reqBody = body == null ? '' : String(body);
            this.addEventListener('load', function () {
              try {
                pushCapture({
                  kind: 'xhr',
                  url: reqUrl,
                  method: reqMethod,
                  requestHeaders: reqHeaders,
                  requestBodyPreview: reqBody,
                  responseStatus: this.status,
                  responsePreview: String(this.responseText || ''),
                  timestamp: Date.now(),
                });
              } catch (error) {
                errors.push({ kind: 'xhr', url: reqUrl, error: String(error) });
              }
            }, { once: true });
          }
          return origSend.apply(this, arguments);
        };

        const restore = () => {
          try { window.fetch = origFetch; } catch {}
          try { xhrProto.open = origOpen; } catch {}
          try { xhrProto.send = origSend; } catch {}
          try { xhrProto.setRequestHeader = origSetRequestHeader; } catch {}
        };

        try {
          if (targetUrl) {
            if (location.href !== targetUrl) {
              location.href = targetUrl;
              await new Promise((resolve) => setTimeout(resolve, 1500));
            } else if (reloadIfSameUrl) {
              location.reload();
              await new Promise((resolve) => setTimeout(resolve, 1500));
            }
          }
          if (clickSearch) {
            const deadline = Date.now() + Math.min(timeoutMs, 15000);
            let clicked = false;
            while (Date.now() < deadline) {
              const candidates = Array.from(document.querySelectorAll('button,[role="button"],.el-button,.ant-btn'))
                .filter((el) => visible(el) && textOf(el).includes('搜索'));
              const target = candidates.find((el) => textOf(el) === '搜索') || candidates[0];
              if (target) {
                target.click();
                clicked = true;
                break;
              }
              await new Promise((resolve) => setTimeout(resolve, 250));
            }
            if (!clicked) return { ok: false, reason: 'search button not found', captures, errors, href: location.href };
          }
          const timedOut = await Promise.race([
            capturePromise.then(() => false),
            new Promise((resolve) => setTimeout(() => resolve(true), timeoutMs)),
          ]);
          if (timedOut) return { ok: false, reason: 'capture timeout', captures, errors, href: location.href };
          return { ok: true, captures, errors, href: location.href };
        } finally {
          restore();
        }
      })()
    `;
}

async function captureRequestViaPageTap(page, { pattern, timeoutMs, targetUrl, clickSearch, label, reloadIfSameUrl = false }) {
    const result = unwrapEvaluateResult(await page.evaluate(buildTapCaptureJs({ pattern, timeoutMs, targetUrl, clickSearch, reloadIfSameUrl })));
    if (!result?.ok) {
        throw new CommandExecutionError(`${label} failed: ${stringValue(result?.reason) || 'unknown reason'} current=${stringValue(result?.href) || '<empty>'}`);
    }
    if (asArray(result.errors).length > 0) {
        const first = asObject(asArray(result.errors)[0]);
        throw new CommandExecutionError(`${label} capture failed: ${stringValue(first.error) || JSON.stringify(first)}`);
    }
    return asArray(result.captures);
}

async function ensureDailyTrafficPage(page) {
    await page.goto(DAILY_TRAFFIC_PAGE_URL);
    await page.wait(4);
    const href = stringValue(unwrapEvaluateResult(await page.evaluate('location.href')));
    if (href.startsWith(BASE_URL)) return;
    throw new CommandExecutionError(`SHEIN daily traffic navigation failed before API fetch: current=${href || '<empty>'}`);
}

async function captureFirstDailyTrafficPage(page, options) {
    await ensureDailyTrafficPage(page);
    let captures;
    try {
        captures = await captureRequestViaPageTap(page, {
            pattern: DAILY_TRAFFIC_API_PATTERN,
            timeoutMs: options.timeoutMs,
            targetUrl: DAILY_TRAFFIC_PAGE_URL,
            clickSearch: true,
            label: 'SHEIN daily traffic first-page response',
        });
    } catch (error) {
        if (!String(error?.message || error).includes('search button not found')) throw error;
        captures = await captureRequestViaPageTap(page, {
            pattern: DAILY_TRAFFIC_API_PATTERN,
            timeoutMs: options.timeoutMs,
            targetUrl: DAILY_TRAFFIC_PAGE_URL,
            clickSearch: false,
            reloadIfSameUrl: true,
            label: 'SHEIN daily traffic first-page response',
        });
    }
    return extractTrafficCaptureContext(captures);
}

async function fetchDailyTrafficPage(page, headers, baseBody, pageNum, date, options) {
    let lastError = '';
    for (let attempt = 1; attempt <= options.retryAttempts; attempt++) {
        try {
            const payload = await page.fetchJson(DAILY_TRAFFIC_API, {
                method: 'POST',
                headers,
                body: buildDailyTrafficBody(baseBody, pageNum, date, options),
                timeoutMs: options.timeoutMs,
            });
            return ensureSuccessfulApiPayload(payload, `daily traffic page ${pageNum} response`);
        } catch (error) {
            lastError = error?.message || String(error);
            if (attempt >= options.retryAttempts) break;
            await page.wait(options.retryDelayMs * attempt / 1000);
        }
    }
    throw new CommandExecutionError(`SHEIN daily traffic page ${pageNum} fetch failed: ${lastError}`);
}

async function fetchDailyTrafficRowsForDate(page, firstPageContext, date, options) {
    const rows = [];
    const pageSize = parsePositiveInt(
        options.pageSize === undefined || options.pageSize === null || options.pageSize === ''
            ? firstPageContext.body?.pageSize
            : options.pageSize,
        '--pageSize',
        100,
    );
    const limitRemaining = options.limitRemaining == null ? Number.MAX_SAFE_INTEGER : options.limitRemaining;

    for (let pageNum = 1; pageNum <= options.maxPages; pageNum++) {
        if (rows.length >= limitRemaining) break;
        const payload = await fetchDailyTrafficPage(page, firstPageContext.headers, firstPageContext.body, pageNum, date, options);
        const info = getInfo(payload);
        const rawRows = getRows(payload);
        const totalCount = getTotalCount(info, rawRows.length);
        if (rawRows.length === 0) break;
        const remaining = Math.max(0, limitRemaining - rows.length);
        rows.push(...rawRows.slice(0, remaining).map((rawRow) => flattenDailyTrafficRow(rawRow, {
            date,
            totalCount,
            pageNum,
            requestUrl: firstPageContext.requestUrl || DAILY_TRAFFIC_API,
        })));
        if (rows.length >= limitRemaining) break;
        if (rawRows.length < pageSize) break;
        if (totalCount !== null && pageNum >= Math.ceil(totalCount / pageSize)) break;
    }

    return rows;
}

export async function collectSheinDailyTrafficRows(page, kwargs) {
    const options = {
        dates: resolveDateRange(kwargs),
        limit: kwargs.limit === undefined || kwargs.limit === null || kwargs.limit === ''
            ? null
            : parsePositiveInt(kwargs.limit, '--limit', 1),
        areaCd: kwargs.areaCd,
        countrySite: kwargs.countrySite,
        pageSize: kwargs.pageSize === undefined || kwargs.pageSize === null || kwargs.pageSize === ''
            ? null
            : parsePositiveInt(kwargs.pageSize, '--pageSize', 100),
        maxPages: kwargs.maxPages === undefined || kwargs.maxPages === null || kwargs.maxPages === ''
            ? Number.MAX_SAFE_INTEGER
            : parsePositiveInt(kwargs.maxPages, '--maxPages', 1),
        timeoutMs: parsePositiveInt(kwargs.requestTimeout, '--requestTimeout', 60) * 1000,
        retryAttempts: parsePositiveInt(kwargs.retryAttempts, '--retryAttempts', 3),
        retryDelayMs: parseNonNegativeInt(kwargs.retryDelayMs, '--retryDelayMs', 1000),
    };
    const firstPageContext = await captureFirstDailyTrafficPage(page, options);
    const collected = [];
    for (const date of options.dates) {
        if (options.limit != null && collected.length >= options.limit) break;
        const limitRemaining = options.limit == null ? null : options.limit - collected.length;
        const rows = await fetchDailyTrafficRowsForDate(page, firstPageContext, date, { ...options, limitRemaining });
        collected.push(...rows);
    }
    return options.limit == null ? collected : collected.slice(0, options.limit);
}

cli({
    site: 'shein',
    name: 'daily-traffic',
    access: 'read',
    description: '拉取 SHEIN 日流量商品分析数据',
    example: 'opencli shein daily-traffic --startDate 2026-07-28 --endDate 2026-07-28 -f json',
    domain: 'sso.geiwohuo.com',
    strategy: Strategy.COOKIE,
    browser: true,
    navigateBefore: false,
    defaultWindowMode: 'foreground',
    defaultFormat: 'json',
    args: [
        { name: 'startDate', help: '开始日期，支持 YYYY-MM-DD 或 YYYYMMDD；不传则默认昨天' },
        { name: 'endDate', help: '结束日期，支持 YYYY-MM-DD 或 YYYYMMDD；不传则取 startDate 或默认昨天' },
        { name: 'areaCd', help: 'SHEIN areaCd；不传则沿用页面请求，最后 fallback 为 cn' },
        { name: 'countrySite', help: 'SHEIN countrySite，逗号分隔；不传则沿用页面请求，最后 fallback 为 shein-all' },
        { name: 'pageSize', type: 'int', help: '列表接口每页数量；不传则沿用页面请求或 100' },
        { name: 'limit', type: 'int', help: '最多返回的商品分析行数，跨日期全局限制' },
        { name: 'maxPages', type: 'int', help: '每天最多拉取页数，调试用' },
        { name: 'timeout', type: 'int', default: 3600, help: '整条 SHEIN 日流量命令总超时时间（秒）' },
        { name: 'requestTimeout', type: 'int', default: 60, help: '单个 SHEIN 页面 API 捕获/请求超时时间（秒）' },
        { name: 'retryAttempts', type: 'int', default: 3, help: '页面 API 网络/5xx 失败重试次数' },
        { name: 'retryDelayMs', type: 'int', default: 1000, help: '页面 API 重试基础间隔毫秒；会按尝试次数线性递增' },
    ],
    columns: SHEIN_DAILY_TRAFFIC_COLUMNS,
    func: collectSheinDailyTrafficRows,
});

export const __test__ = {
    normalizeDateInput,
    resolveDateRange,
    normalizeCountrySite,
    filterReplayableHeaders,
    extractTrafficCaptureContext,
    buildDailyTrafficBody,
    flattenDailyTrafficRow,
    fetchDailyTrafficRowsForDate,
    getRows,
    getTotalCount,
};
