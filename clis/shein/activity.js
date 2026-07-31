import { CommandExecutionError } from '@jackwener/opencli/errors';
import { log } from '@jackwener/opencli/logger';
import { cli, Strategy } from '@jackwener/opencli/registry';

const BASE_URL = 'https://sso.geiwohuo.com';
const ACTIVITY_LIST_PAGE_URL = `${BASE_URL}/#/mars/tools/list`;
const ACTIVITY_DETAIL_ROUTE_PREFIX = '/#/mrs/tools/activity/obm-time-limit-info';
const ACTIVITY_LIST_API = `${BASE_URL}/mrs-api-prefix/promotion/obm/query_obm_activity_list`;
const ACTIVITY_DETAIL_API = `${BASE_URL}/mrs-api-prefix/promotion/simple_platform/query_goods_detail`;
const ACTIVITY_LIST_API_PATTERN = '/mrs-api-prefix/promotion/obm/query_obm_activity_list';

export const SHEIN_ACTIVITY_COLUMNS = [
    'record_type',
    'snapshot_date',
    'store',
    'profile',
    'request_url',
    'list_request_url',
    'detail_request_url',
    'queried_insert_start_time',
    'queried_insert_end_time',
    'queried_page_size',
    'queried_type_id',
    'queried_time_zone',
    'queried_system',
    'activity_total_count',
    'activity_total_pages',
    'activity_page_num',
    'detail_total_count',
    'detail_total_pages',
    'detail_page_num',
    'activity_id',
    'activity_name',
    'activity_status',
    'activity_type_id',
    'type_id',
    'activity_type_name',
    'site',
    'country',
    'creator',
    'created_at',
    'updated_at',
    'start_time',
    'end_time',
    'terminate_time',
    'state',
    'store_code',
    'supplier_id',
    'source_store_name',
    'tool_name',
    'raw_activity_json',
    'goods_id',
    'skc',
    'image_url',
    'sku_supplier_no',
    'attend_num_sum',
    'stock_num',
    'ivt_num',
    'inventory_num',
    'goods_product_act_price',
    'goods_max_product_act_price',
    'goods_is_effective',
    'goods_failed_reason',
    'goods_state',
    'goods_is_del',
    'goods_currency',
    'goods_supply_price_new',
    'goods_supply_price',
    'goods_us_supply_price',
    'goods_eur_supply_price',
    'goods_uk_supply_price',
    'goods_mxn_supply_price',
    'is_sale_attribute',
    'pricing_type',
    'product_tag',
    'sku_count',
    'sku',
    'sku_currency',
    'sku_supply_price_new',
    'sku_product_act_price',
    'sku_max_product_act_price',
    'sku_supply_price',
    'sku_us_supply_price',
    'sku_eur_supply_price',
    'sku_uk_supply_price',
    'sku_mxn_supply_price',
    'sku_main_attr_names',
    'sku_sale_attr_names',
    'sku_attr_info_list_json',
    'goods_country_attr_info_list_json',
    'sku_info_list_json',
    'raw_detail_json',
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

function activityLog(debug, message) {
    if (debug) log.status(`[shein activity] ${message}`);
    else log.verbose(`[shein activity] ${message}`);
}

function summarizeTexts(values, limit = 8) {
    return asArray(values)
        .map((value) => stringValue(value).replace(/\s+/g, ' ').trim())
        .filter(Boolean)
        .slice(0, limit)
        .join(' | ');
}

function summarizePageState(state) {
    const pageState = asObject(state);
    const href = stringValue(pageState.href) || '<empty>';
    const flags = `createRecord=${pageState.hasCreateRecord === true ? 'yes' : 'no'} search=${pageState.hasSearchButton === true ? 'yes' : 'no'}`;
    const texts = summarizeTexts(pageState.availableTexts);
    return `${href} ${flags}${texts ? ` texts=${texts}` : ''}`;
}

function scalar(value) {
    if (value === null || value === undefined) return '';
    if (typeof value === 'object') return '';
    return value;
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

function formatLocalDate(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
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

function defaultSnapshotDate(now = new Date()) {
    const date = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    date.setDate(date.getDate() - 1);
    return formatLocalDate(date);
}

function addMonthsUtc(isoDate, months) {
    const year = Number(isoDate.slice(0, 4));
    const monthIndex = Number(isoDate.slice(5, 7)) - 1;
    const day = Number(isoDate.slice(8, 10));
    const firstOfTarget = new Date(Date.UTC(year, monthIndex + months, 1));
    const lastDayOfTargetMonth = new Date(Date.UTC(
        firstOfTarget.getUTCFullYear(),
        firstOfTarget.getUTCMonth() + 1,
        0,
    )).getUTCDate();
    firstOfTarget.setUTCDate(Math.min(day, lastDayOfTargetMonth));
    return formatIsoDate(firstOfTarget);
}

function resolveActivityQueryWindow(kwargs = {}, capturedBody = {}, now = new Date()) {
    const snapshotDate = normalizeDateInput(kwargs.snapshotDate, '--snapshotDate') || defaultSnapshotDate(now);
    const captured = asObject(capturedBody);
    const insertStartTime = stringValue(kwargs.insertStartTime).trim()
        || stringValue(captured.insert_start_time ?? captured.insertStartTime).trim()
        || `${addMonthsUtc(snapshotDate, -6)} 00:00:00`;
    const insertEndTime = stringValue(kwargs.insertEndTime).trim()
        || stringValue(captured.insert_end_time ?? captured.insertEndTime).trim()
        || `${snapshotDate} 23:59:59`;
    return { snapshotDate, insertStartTime, insertEndTime };
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
        'priority',
    ]);
    for (const [name, value] of Object.entries(lowered)) {
        if (blocked.has(name)) continue;
        if (name.startsWith('sec-') || name.startsWith(':') || name.startsWith('proxy-')) continue;
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

function extractActivityCaptureContext(entries) {
    const match = [...asArray(entries)].reverse().find((entry) => {
        const row = asObject(entry);
        return urlMatchesApi(row.url, ACTIVITY_LIST_API)
            && stringValue(row.responsePreview).trim()
            && numberOrNull(row.responseStatus) !== null
            && numberOrNull(row.responseStatus) < 400;
    });
    if (!match) {
        throw new CommandExecutionError('Failed to capture SHEIN activity list first-page request');
    }
    const requestBody = asObject(parseJsonText(match.requestBodyPreview, 'SHEIN activity list request body'));
    const response = ensureSuccessfulApiPayload(
        parseJsonText(match.responsePreview, 'SHEIN activity list response'),
        'activity list response',
    );
    return {
        headers: filterReplayableHeaders(match.requestHeaders),
        body: requestBody,
        response,
        requestUrl: stringValue(match.url) || ACTIVITY_LIST_API,
    };
}

function optionValue(raw, captured, fallback) {
    if (raw !== undefined && raw !== null && stringValue(raw).trim() !== '') return raw;
    if (captured !== undefined && captured !== null && stringValue(captured).trim() !== '') return captured;
    return fallback;
}

function buildActivityListBody(firstPageBody, pageNum, options = {}) {
    const captured = asObject(firstPageBody);
    const window = resolveActivityQueryWindow(options, captured);
    const pageSize = parsePositiveInt(optionValue(options.pageSize, captured.page_size ?? captured.pageSize, 100), '--pageSize', 100);
    return {
        ...captured,
        insert_start_time: window.insertStartTime,
        insert_end_time: window.insertEndTime,
        page_num: pageNum,
        page_size: pageSize,
        type_id: optionValue(options.typeId, captured.type_id ?? captured.typeId, 31),
        system: stringValue(optionValue(options.system, captured.system, 'mrs')).trim() || 'mrs',
        time_zone: stringValue(optionValue(options.timeZone, captured.time_zone ?? captured.timeZone, 'Asia/Shanghai')).trim() || 'Asia/Shanghai',
    };
}

function buildActivityDetailBody(activityId, pageNum, options = {}) {
    return {
        activity_id: stringValue(activityId),
        page_num: pageNum,
        page_size: parsePositiveInt(options.pageSize, '--pageSize', 100),
    };
}

function splitActivityIds(raw) {
    if (raw === undefined || raw === null || raw === '') return [];
    if (Array.isArray(raw)) return uniqueStrings(raw);
    const text = stringValue(raw).trim();
    if (!text) return [];
    if (text.startsWith('[')) {
        try {
            const parsed = JSON.parse(text);
            if (Array.isArray(parsed)) return uniqueStrings(parsed);
        } catch {}
    }
    return uniqueStrings(text.split(/[\s,\-]+/));
}

function uniqueStrings(values) {
    const seen = new Set();
    const result = [];
    for (const value of values) {
        const text = stringValue(value).trim();
        if (!text || seen.has(text)) continue;
        seen.add(text);
        result.push(text);
    }
    return result;
}

function extractActivityId(row) {
    const source = asObject(row);
    return stringValue(source.activity_id ?? source.activityId ?? source.prom_id ?? source.promId ?? source.id).trim();
}

function extractActivityIds(rows) {
    return uniqueStrings(asRecordArray(rows).map(extractActivityId));
}

function getInfo(payload) {
    for (const candidate of [
        payload?.info,
        payload?.data,
        payload?.result,
        payload?.payload?.info,
        payload?.payload?.data,
        payload?.payload?.result,
        payload,
    ]) {
        const source = asObject(candidate);
        if (Object.keys(source).length > 0) return source;
    }
    return {};
}

function findRecordArray(value, depth = 0) {
    if (depth > 4) return [];
    const direct = asRecordArray(value);
    if (direct.length > 0) return direct;
    const source = asObject(value);
    for (const key of ['list', 'data', 'rows', 'records', 'items', 'result', 'results']) {
        const rows = findRecordArray(source[key], depth + 1);
        if (rows.length > 0) return rows;
    }
    for (const key of ['info', 'payload']) {
        const rows = findRecordArray(source[key], depth + 1);
        if (rows.length > 0) return rows;
    }
    return [];
}

function getRows(payload) {
    return findRecordArray(payload);
}

function findFirstNumber(value, keys, depth = 0) {
    if (depth > 4) return null;
    const source = asObject(value);
    for (const key of keys) {
        const parsed = numberOrNull(source[key]);
        if (parsed !== null) return parsed;
    }
    for (const key of ['info', 'payload', 'data', 'result', 'meta', 'pagination', 'page']) {
        const parsed = findFirstNumber(source[key], keys, depth + 1);
        if (parsed !== null) return parsed;
    }
    return null;
}

function getTotalCount(infoOrPayload, fallbackRows = 0) {
    return findFirstNumber(infoOrPayload, ['total', 'totalCount', 'total_count', 'totalNum', 'total_num', 'count']) ?? fallbackRows;
}

function getTotalPages(infoOrPayload, pageSize, totalCount) {
    const explicit = findFirstNumber(infoOrPayload, ['total_pages', 'totalPages', 'page_count', 'pageCount', 'pages']);
    if (explicit !== null && explicit > 0) return explicit;
    if (totalCount > 0) return Math.ceil(totalCount / pageSize);
    return 0;
}

function getKnownTotalPages(infoOrPayload, pageSize) {
    const explicitPages = findFirstNumber(infoOrPayload, ['total_pages', 'totalPages', 'page_count', 'pageCount', 'pages']);
    if (explicitPages !== null && explicitPages > 0) return explicitPages;
    const explicitTotal = findFirstNumber(infoOrPayload, ['total', 'totalCount', 'total_count', 'totalNum', 'total_num', 'count']);
    if (explicitTotal !== null && explicitTotal > 0) return Math.ceil(explicitTotal / pageSize);
    return null;
}

function firstNonBlank(source, keys) {
    for (const key of keys) {
        const value = source[key];
        if (value !== null && value !== undefined && stringValue(value).trim() !== '') return value;
    }
    return '';
}

function joinAttrNames(items) {
    return asRecordArray(items).map((item) => {
        const source = asObject(item);
        return stringValue(source.attr_value_name ?? source.attrValueName ?? source.value_name ?? source.valueName ?? source.name).trim();
    }).filter(Boolean).join(' | ');
}

function skuRowsFromDetail(detail) {
    const row = asObject(detail);
    const skuRows = asRecordArray(row.sku_info_list ?? row.skuInfoList ?? row.sku_list ?? row.skuList);
    return skuRows.length > 0 ? skuRows : [{}];
}

function baseActivityFields(activity) {
    const row = asObject(activity);
    return {
        activity_id: stringValue(firstNonBlank(row, ['activity_id', 'activityId', 'prom_id', 'promId', 'id'])),
        activity_name: scalar(firstNonBlank(row, ['activity_name', 'activityName', 'act_name', 'actName', 'name'])),
        activity_status: scalar(firstNonBlank(row, ['activity_status', 'activityStatus', 'status'])),
        activity_type_id: scalar(firstNonBlank(row, ['activity_type_id', 'activityTypeId', 'type_id', 'typeId'])),
        type_id: scalar(firstNonBlank(row, ['type_id', 'typeId', 'activity_type_id', 'activityTypeId'])),
        activity_type_name: scalar(firstNonBlank(row, ['activity_type_name', 'activityTypeName', 'type_name', 'typeName'])),
        site: scalar(firstNonBlank(row, ['site', 'main_site', 'mainSite'])),
        country: scalar(row.country),
        creator: scalar(firstNonBlank(row, ['creator', 'create_user', 'createUser'])),
        created_at: scalar(firstNonBlank(row, ['created_at', 'createdAt', 'insert_time', 'insertTime'])),
        updated_at: scalar(firstNonBlank(row, ['updated_at', 'updatedAt', 'update_time', 'updateTime'])),
        start_time: scalar(firstNonBlank(row, ['start_time', 'startTime', 'activity_start_time', 'begin_time'])),
        end_time: scalar(firstNonBlank(row, ['end_time', 'endTime', 'activity_end_time', 'finish_time'])),
        terminate_time: scalar(firstNonBlank(row, ['terminate_time', 'terminated_time', 'stop_time', 'close_time', 'cancel_time', 'abort_time'])),
        state: scalar(firstNonBlank(row, ['state', 'activity_state', 'activityState'])),
        store_code: scalar(firstNonBlank(row, ['store_code', 'storeCode'])),
        supplier_id: scalar(firstNonBlank(row, ['supplier_id', 'supplierId'])),
        source_store_name: scalar(firstNonBlank(row, ['store_name', 'storeName'])),
        tool_name: scalar(firstNonBlank(row, ['tool_name', 'toolName'])),
    };
}

function detailFields(detail, sku) {
    const row = asObject(detail);
    const skuRow = asObject(sku);
    return {
        goods_id: scalar(firstNonBlank(row, ['goods_id', 'goodsId'])),
        skc: scalar(firstNonBlank(row, ['skc', 'goods_sn', 'goodsSn'])),
        image_url: normalizeUrl(firstNonBlank(row, ['image_url', 'imageUrl', 'img_url', 'imgUrl', 'goods_img', 'goodsImg'])),
        sku_supplier_no: scalar(firstNonBlank(row, ['sku_supplier_no', 'skuSupplierNo', 'supplier_sku', 'supplierSku'])),
        attend_num_sum: scalar(firstNonBlank(row, ['attend_num_sum', 'attendNumSum'])),
        stock_num: scalar(firstNonBlank(row, ['stock_num', 'stockNum'])),
        ivt_num: scalar(firstNonBlank(row, ['ivt_num', 'ivtNum'])),
        inventory_num: scalar(firstNonBlank(row, ['inventory_num', 'inventoryNum'])),
        goods_product_act_price: scalar(firstNonBlank(row, ['goods_product_act_price', 'goodsProductActPrice', 'product_act_price'])),
        goods_max_product_act_price: scalar(firstNonBlank(row, ['goods_max_product_act_price', 'goodsMaxProductActPrice'])),
        goods_is_effective: scalar(firstNonBlank(row, ['goods_is_effective', 'goodsIsEffective'])),
        goods_failed_reason: scalar(firstNonBlank(row, ['goods_failed_reason', 'goodsFailedReason'])),
        goods_state: scalar(firstNonBlank(row, ['goods_state', 'goodsState'])),
        goods_is_del: scalar(firstNonBlank(row, ['goods_is_del', 'goodsIsDel'])),
        goods_currency: scalar(firstNonBlank(row, ['goods_currency', 'goodsCurrency', 'currency'])),
        goods_supply_price_new: scalar(firstNonBlank(row, ['goods_supply_price_new', 'goodsSupplyPriceNew'])),
        goods_supply_price: scalar(firstNonBlank(row, ['goods_supply_price', 'goodsSupplyPrice'])),
        goods_us_supply_price: scalar(firstNonBlank(row, ['goods_us_supply_price', 'goodsUsSupplyPrice'])),
        goods_eur_supply_price: scalar(firstNonBlank(row, ['goods_eur_supply_price', 'goodsEurSupplyPrice'])),
        goods_uk_supply_price: scalar(firstNonBlank(row, ['goods_uk_supply_price', 'goodsUkSupplyPrice'])),
        goods_mxn_supply_price: scalar(firstNonBlank(row, ['goods_mxn_supply_price', 'goodsMxnSupplyPrice'])),
        is_sale_attribute: scalar(firstNonBlank(row, ['is_sale_attribute', 'isSaleAttribute'])),
        pricing_type: scalar(firstNonBlank(row, ['pricing_type', 'pricingType'])),
        product_tag: scalar(firstNonBlank(row, ['product_tag', 'productTag'])),
        sku_count: scalar(firstNonBlank(row, ['sku_count', 'skuCount'])),
        sku: scalar(firstNonBlank(skuRow, ['sku', 'sku_sn', 'skuSn'])),
        sku_currency: scalar(firstNonBlank(skuRow, ['sku_currency', 'skuCurrency', 'currency'])),
        sku_supply_price_new: scalar(firstNonBlank(skuRow, ['sku_supply_price_new', 'skuSupplyPriceNew'])),
        sku_product_act_price: scalar(firstNonBlank(skuRow, ['sku_product_act_price', 'skuProductActPrice', 'product_act_price'])),
        sku_max_product_act_price: scalar(firstNonBlank(skuRow, ['sku_max_product_act_price', 'skuMaxProductActPrice'])),
        sku_supply_price: scalar(firstNonBlank(skuRow, ['sku_supply_price', 'skuSupplyPrice'])),
        sku_us_supply_price: scalar(firstNonBlank(skuRow, ['sku_us_supply_price', 'skuUsSupplyPrice'])),
        sku_eur_supply_price: scalar(firstNonBlank(skuRow, ['sku_eur_supply_price', 'skuEurSupplyPrice'])),
        sku_uk_supply_price: scalar(firstNonBlank(skuRow, ['sku_uk_supply_price', 'skuUkSupplyPrice'])),
        sku_mxn_supply_price: scalar(firstNonBlank(skuRow, ['sku_mxn_supply_price', 'skuMxnSupplyPrice'])),
        sku_main_attr_names: joinAttrNames(skuRow.main_attr_info_list ?? skuRow.mainAttrInfoList),
        sku_sale_attr_names: joinAttrNames(skuRow.sale_attr_info_list ?? skuRow.saleAttrInfoList),
        sku_attr_info_list_json: asArray(skuRow.attr_info_list ?? skuRow.attrInfoList),
        goods_country_attr_info_list_json: asArray(row.country_attr_info_list ?? row.countryAttrInfoList),
        sku_info_list_json: asArray(row.sku_info_list ?? row.skuInfoList ?? row.sku_list ?? row.skuList),
    };
}

function orderedRow(values) {
    const row = {};
    for (const column of SHEIN_ACTIVITY_COLUMNS) row[column] = values[column] ?? '';
    return row;
}

function flattenActivityRows(activity, detailRows, meta = {}) {
    const activityFields = baseActivityFields(activity);
    const common = {
        snapshot_date: normalizeDateInput(meta.snapshotDate, 'activity row snapshot_date') || '',
        store: stringValue(meta.store),
        profile: stringValue(meta.profile),
        request_url: stringValue(meta.detailRequestUrl || meta.listRequestUrl),
        list_request_url: stringValue(meta.listRequestUrl),
        detail_request_url: stringValue(meta.detailRequestUrl),
        queried_insert_start_time: stringValue(meta.insertStartTime),
        queried_insert_end_time: stringValue(meta.insertEndTime),
        queried_page_size: meta.pageSize ?? '',
        queried_type_id: meta.typeId ?? activityFields.type_id ?? '',
        queried_time_zone: stringValue(meta.timeZone),
        queried_system: stringValue(meta.system),
        activity_total_count: meta.activityTotalCount ?? '',
        activity_total_pages: meta.activityTotalPages ?? '',
        activity_page_num: meta.activityPageNum ?? '',
        detail_total_count: meta.detailTotalCount ?? '',
        detail_total_pages: meta.detailTotalPages ?? '',
        detail_page_num: meta.detailPageNum ?? '',
        ...activityFields,
        raw_activity_json: asObject(activity),
    };
    const details = asRecordArray(detailRows);
    if (details.length === 0) {
        return [orderedRow({
            ...common,
            record_type: 'activity_list_only',
            raw_detail_json: {},
            raw_json: asObject(activity),
        })];
    }
    const rows = [];
    for (const detail of details) {
        for (const sku of skuRowsFromDetail(detail)) {
            rows.push(orderedRow({
                ...common,
                record_type: 'activity_detail',
                ...detailFields(detail, sku),
                raw_detail_json: asObject(detail),
                raw_json: asObject(detail),
            }));
        }
    }
    return rows;
}

async function maybeWait(page, minMs, maxMs) {
    const min = parseNonNegativeInt(minMs, '--requestDelayMinMs', 0);
    const max = parseNonNegativeInt(maxMs, '--requestDelayMaxMs', min);
    const delayMs = max <= min ? min : min + Math.floor(Math.random() * (max - min + 1));
    if (delayMs > 0) await page.wait(delayMs / 1000);
}

async function fetchJsonWithRetry(page, url, requestOptions, label, options) {
    let lastError = '';
    for (let attempt = 1; attempt <= options.retryAttempts; attempt++) {
        try {
            const payload = await page.fetchJson(url, requestOptions);
            return ensureSuccessfulApiPayload(payload, label);
        } catch (error) {
            lastError = error?.message || String(error);
            if (attempt >= options.retryAttempts) break;
            await page.wait(options.retryDelayMs * attempt / 1000);
        }
    }
    throw new CommandExecutionError(`SHEIN ${label} fetch failed: ${lastError}`);
}

async function fetchActivityListPage(page, headers, baseBody, pageNum, options) {
    await maybeWait(page, options.requestDelayMinMs, options.requestDelayMaxMs);
    activityLog(options.debug, `fetch list page ${pageNum}: page_size=${parsePositiveInt(options.pageSize, '--pageSize', 100)}`);
    return fetchJsonWithRetry(page, ACTIVITY_LIST_API, {
        method: 'POST',
        headers,
        body: buildActivityListBody(baseBody, pageNum, options),
        timeoutMs: options.timeoutMs,
    }, `activity list page ${pageNum} response`, options);
}

function detailHeaders(baseHeaders, activityId) {
    const route = `${ACTIVITY_DETAIL_ROUTE_PREFIX}/${encodeURIComponent(activityId)}`;
    const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Shanghai';
    return {
        ...filterReplayableHeaders(baseHeaders),
        'origin-url': `${BASE_URL}${route}`,
        'x-bbl-route': route.replace('/#', ''),
        'x-req-zone-id': timezone,
        'x-req-sso-zone-id': timezone,
        lan: 'CN',
        'x-lt-language': 'CN',
    };
}

async function fetchActivityDetailPages(page, headers, activity, options) {
    const activityId = extractActivityId(activity);
    if (!activityId) return [];
    const rows = [];
    const pageSize = parsePositiveInt(options.pageSize, '--pageSize', 100);
    activityLog(options.debug, `fetch detail start: activity_id=${activityId}`);
    for (let pageNum = 1; pageNum <= options.maxDetailPages; pageNum++) {
        await maybeWait(page, options.requestDelayMinMs, options.requestDelayMaxMs);
        activityLog(options.debug, `fetch detail page ${pageNum}: activity_id=${activityId} page_size=${pageSize}`);
        const payload = await fetchJsonWithRetry(page, ACTIVITY_DETAIL_API, {
            method: 'POST',
            headers: detailHeaders(headers, activityId),
            body: buildActivityDetailBody(activityId, pageNum, options),
            timeoutMs: options.timeoutMs,
        }, `activity detail ${activityId} page ${pageNum} response`, options);
        const rawRows = getRows(payload);
        const totalCount = getTotalCount(payload, rawRows.length);
        const knownTotalPages = getKnownTotalPages(payload, pageSize);
        activityLog(options.debug, `detail page result: activity_id=${activityId} page=${pageNum} rows=${rawRows.length} total=${totalCount} pages=${knownTotalPages ?? '<unknown>'}`);
        if (rawRows.length === 0) {
            if (pageNum === 1 && rows.length === 0) {
                rows.push(...flattenActivityRows(activity, [], {
                    ...options,
                    activityId,
                    detailPageNum: pageNum,
                    detailTotalCount: totalCount,
                    detailTotalPages: knownTotalPages ?? '',
                    detailRequestUrl: ACTIVITY_DETAIL_API,
                }));
            }
            break;
        }
        rows.push(...flattenActivityRows(activity, rawRows, {
            ...options,
            activityId,
            detailPageNum: pageNum,
            detailTotalCount: totalCount,
            detailTotalPages: knownTotalPages ?? '',
            detailRequestUrl: ACTIVITY_DETAIL_API,
        }));
        if (rawRows.length < pageSize) break;
        if (knownTotalPages !== null && pageNum >= knownTotalPages) break;
    }
    return rows;
}

async function mapConcurrent(items, concurrency, worker) {
    const results = new Array(items.length);
    let nextIndex = 0;
    async function runWorker() {
        while (nextIndex < items.length) {
            const index = nextIndex;
            nextIndex += 1;
            results[index] = await worker(items[index], index);
        }
    }
    const workerCount = Math.max(1, Math.min(parsePositiveInt(concurrency, '--detailConcurrency', 5), items.length || 1));
    await Promise.all(Array.from({ length: workerCount }, runWorker));
    return results;
}

async function fetchActivityRows(page, firstPageContext, options) {
    const pageSize = parsePositiveInt(options.pageSize, '--pageSize', 100);
    const requestedIds = splitActivityIds(options.activityIds);
    const activities = [];
    activityLog(options.debug, `fetch rows start: requested_ids=${requestedIds.length} max_list_pages=${options.maxListPages} max_detail_pages=${options.maxDetailPages}`);
    if (requestedIds.length > 0) {
        activities.push(...requestedIds.map((id) => ({ activity_id: id })));
    } else {
        for (let pageNum = 1; pageNum <= options.maxListPages; pageNum++) {
            if (options.limitActivities != null && activities.length >= options.limitActivities) break;
            const payload = await fetchActivityListPage(page, firstPageContext.headers, firstPageContext.body, pageNum, options);
            const rawRows = getRows(payload);
            const totalCount = getTotalCount(payload, rawRows.length);
            const knownTotalPages = getKnownTotalPages(payload, pageSize);
            activityLog(options.debug, `list page result: page=${pageNum} rows=${rawRows.length} total=${totalCount} pages=${knownTotalPages ?? '<unknown>'}`);
            const remaining = options.limitActivities == null ? rawRows.length : Math.max(0, options.limitActivities - activities.length);
            const pageActivities = rawRows.slice(0, remaining).map((activity) => ({
                ...activity,
                __activityPageNum: pageNum,
                __activityTotalCount: totalCount,
                __activityTotalPages: knownTotalPages ?? '',
            }));
            activities.push(...pageActivities);
            if (rawRows.length === 0) break;
            if (rawRows.length < pageSize) break;
            if (knownTotalPages !== null && pageNum >= knownTotalPages) break;
        }
    }

    const firstActivityId = extractActivityId(activities[0]);
    activityLog(options.debug, `activity list collected: activities=${activities.length} first_activity_id=${firstActivityId || '<empty>'}`);
    if (firstActivityId) {
        await ensureActivityDetailPage(page, firstActivityId, options);
    }

    const detailGroups = await mapConcurrent(activities, options.detailConcurrency, async (activity) => fetchActivityDetailPages(
        page,
        firstPageContext.headers,
        activity,
        {
            ...options,
            listRequestUrl: firstPageContext.requestUrl || ACTIVITY_LIST_API,
            activityPageNum: activity.__activityPageNum ?? '',
            activityTotalCount: activity.__activityTotalCount ?? '',
            activityTotalPages: activity.__activityTotalPages ?? '',
        },
    ));
    const rows = detailGroups.flat();
    activityLog(options.debug, `fetch rows completed: output_rows=${rows.length}`);
    return options.limitRows == null ? rows : rows.slice(0, options.limitRows);
}

function buildTapCaptureJs({ pattern, timeoutMs, targetUrl, clickText = '', reloadIfSameUrl = false }) {
    return `
      (async () => {
        const pattern = ${JSON.stringify(pattern)};
        const timeoutMs = ${JSON.stringify(timeoutMs)};
        const targetUrl = ${JSON.stringify(targetUrl || '')};
        const clickText = ${JSON.stringify(clickText || '')};
        const reloadIfSameUrl = ${reloadIfSameUrl ? 'true' : 'false'};
        const captures = [];
        const errors = [];
        let finished = false;
        let resolveCapture;
        const capturePromise = new Promise((resolve) => { resolveCapture = resolve; });
        const visible = (el) => {
          if (!(el instanceof HTMLElement)) return false;
          const style = window.getComputedStyle(el);
          const rect = el.getBoundingClientRect();
          return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
        };
        const textOf = (el) => (el?.textContent || '').replace(/\\s+/g, ' ').trim();
        const compactTextOf = (el) => textOf(el).replace(/\\s+/g, '');
        const resolveClickable = (el) => {
          let current = el;
          for (let depth = 0; current && depth < 5; depth += 1) {
            const tag = String(current.tagName || '').toLowerCase();
            const role = String(current.getAttribute?.('role') || '').toLowerCase();
            if (tag === 'button' || tag === 'a' || role === 'button' || typeof current.onclick === 'function') {
              return current;
            }
            current = current.parentElement;
          }
          return el;
        };
        const visibleTexts = () => Array.from(document.querySelectorAll('button,[role="button"],a,.el-button,.ant-btn,span,div'))
          .filter(visible)
          .map((el) => textOf(el))
          .filter(Boolean)
          .slice(0, 30);
        const candidateScore = (el) => {
          const rect = el.getBoundingClientRect();
          const tag = String(el.tagName || '').toLowerCase();
          const role = String(el.getAttribute?.('role') || '').toLowerCase();
          const isControl = tag === 'button' || tag === 'a' || role === 'button' || el.classList?.contains('el-button') || el.classList?.contains('ant-btn');
          return [
            isControl ? 0 : 1,
            compactTextOf(el).length,
            Math.round(rect.width * rect.height),
          ];
        };
        const compareCandidates = (a, b) => {
          const left = candidateScore(a);
          const right = candidateScore(b);
          for (let i = 0; i < left.length; i += 1) {
            if (left[i] !== right[i]) return left[i] - right[i];
          }
          return 0;
        };
        const dismissShownDialogs = () => {
          Array.from(document.querySelectorAll('div.so-modal-show')).forEach((el) => {
            try { el.classList.remove('so-modal-show'); } catch {}
          });
        };
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
          const reqHeaders = readHeaders(init.headers || request?.headers);
          const reqBody = await readBody(init.body, request);
          const response = await origFetch.apply(this, args);
          if (pattern && reqUrl.includes(pattern)) {
            try {
              pushCapture({ kind: 'fetch', url: reqUrl, requestHeaders: reqHeaders, requestBodyPreview: reqBody, responseStatus: response.status, responsePreview: await response.clone().text(), timestamp: Date.now() });
            } catch (error) {
              errors.push({ kind: 'fetch', url: reqUrl, error: String(error) });
            }
          }
          return response;
        };
        xhrProto.open = function (method, url) {
          this.__opencliSheinActivityUrl = String(url || '');
          this.__opencliSheinActivityHeaders = {};
          return origOpen.apply(this, arguments);
        };
        xhrProto.setRequestHeader = function (name, value) {
          try { this.__opencliSheinActivityHeaders[String(name)] = String(value); } catch {}
          return origSetRequestHeader.apply(this, arguments);
        };
        xhrProto.send = function (body) {
          const reqUrl = String(this.__opencliSheinActivityUrl || '');
          if (pattern && reqUrl.includes(pattern)) {
            const reqHeaders = this.__opencliSheinActivityHeaders || {};
            const reqBody = body == null ? '' : String(body);
            this.addEventListener('load', function () {
              try {
                pushCapture({ kind: 'xhr', url: reqUrl, requestHeaders: reqHeaders, requestBodyPreview: reqBody, responseStatus: this.status, responsePreview: String(this.responseText || ''), timestamp: Date.now() });
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
          if (clickText) {
            dismissShownDialogs();
            const deadline = Date.now() + Math.min(timeoutMs, 15000);
            let clicked = false;
            const normalizedClickText = String(clickText).replace(/\\s+/g, '');
            while (Date.now() < deadline) {
              const primaryCandidates = Array.from(document.querySelectorAll('button,[role="button"],a,.el-button,.ant-btn'))
                .filter((el) => visible(el) && compactTextOf(el).includes(normalizedClickText));
              const fallbackCandidates = Array.from(document.querySelectorAll('span,div'))
                .filter((el) => visible(el) && compactTextOf(el).includes(normalizedClickText));
              const candidates = [...primaryCandidates, ...fallbackCandidates].sort(compareCandidates);
              const target = candidates.find((el) => compactTextOf(el) === normalizedClickText) || candidates[0];
              if (target) {
                const clickable = resolveClickable(target);
                try { clickable.scrollIntoView?.({ block: 'center', inline: 'center', behavior: 'instant' }); } catch {}
                clickable.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, composed: true }));
                clickable.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true, composed: true }));
                clickable.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, composed: true }));
                try { clickable.click?.(); } catch {}
                clicked = true;
                break;
              }
              await new Promise((resolve) => setTimeout(resolve, 250));
            }
            if (!clicked) return { ok: false, reason: 'button not found: ' + clickText, captures, errors, href: location.href, availableTexts: visibleTexts() };
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

async function captureRequestViaPageTap(page, { pattern, timeoutMs, targetUrl, clickText, label, reloadIfSameUrl = false }) {
    const result = unwrapEvaluateResult(await page.evaluate(buildTapCaptureJs({ pattern, timeoutMs, targetUrl, clickText, reloadIfSameUrl })));
    if (!result?.ok) {
        const availableTexts = asArray(result?.availableTexts).join(' | ');
        throw new CommandExecutionError(`${label} failed: ${stringValue(result?.reason) || 'unknown reason'} current=${stringValue(result?.href) || '<empty>'}${availableTexts ? ` available=${availableTexts}` : ''}`);
    }
    if (asArray(result.errors).length > 0) {
        const first = asObject(asArray(result.errors)[0]);
        throw new CommandExecutionError(`${label} capture failed: ${stringValue(first.error) || JSON.stringify(first)}`);
    }
    return asArray(result.captures);
}

function buildActivityListPageStateJs() {
    return `
      (() => {
        const visible = (el) => {
          if (!(el instanceof HTMLElement)) return false;
          const style = window.getComputedStyle(el);
          const rect = el.getBoundingClientRect();
          return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
        };
        const textOf = (el) => (el?.textContent || '').replace(/\\s+/g, ' ').trim();
        const candidates = Array.from(document.querySelectorAll('button,[role="button"],span,div,a'))
          .filter(visible)
          .map((el) => textOf(el))
          .filter(Boolean);
        const searchButtons = Array.from(document.querySelectorAll('button,[role="button"],a,.el-button,.ant-btn'))
          .filter((el) => visible(el) && textOf(el).replace(/\\s+/g, '') === '搜索');
        return {
          href: location.href,
          hasCreateRecord: candidates.some((text) => text.replace(/\\s+/g, '').includes('创建记录')),
          hasSearchButton: searchButtons.length > 0,
          availableTexts: candidates.slice(0, 30),
        };
      })()
    `;
}

async function readActivityListPageState(page) {
    return asObject(unwrapEvaluateResult(await page.evaluate(buildActivityListPageStateJs())));
}

async function ensureActivityPage(page, options = {}) {
    const attempts = parsePositiveInt(options.attempts, 'activity page navigation attempts', 3);
    let lastState = {};
    for (let attempt = 1; attempt <= attempts; attempt++) {
        activityLog(options.debug, `activity page navigation attempt ${attempt}/${attempts}: goto ${ACTIVITY_LIST_PAGE_URL}`);
        await page.goto(ACTIVITY_LIST_PAGE_URL, { waitUntil: 'none' });
        await page.wait(attempt === 1 ? 4 : 2);
        lastState = await readActivityListPageState(page);
        activityLog(options.debug, `activity page state attempt ${attempt}/${attempts}: ${summarizePageState(lastState)}`);
        const href = stringValue(lastState.href);
        if (href.startsWith(BASE_URL) && lastState.hasCreateRecord === true) {
            activityLog(options.debug, `activity page ready: attempt=${attempt}`);
            return lastState;
        }
    }
    const href = stringValue(lastState.href);
    const availableTexts = asArray(lastState.availableTexts).join(' | ');
    throw new CommandExecutionError(`SHEIN activity list page not ready before API fetch: current=${href || '<empty>'}${availableTexts ? ` available=${availableTexts}` : ''}`);
}

async function ensureActivityDetailPage(page, activityId, options = {}) {
    const normalizedActivityId = stringValue(activityId).trim();
    if (!normalizedActivityId) return;
    const targetUrl = `${BASE_URL}${ACTIVITY_DETAIL_ROUTE_PREFIX}/${encodeURIComponent(normalizedActivityId)}`;
    activityLog(options.debug, `activity detail navigation: activity_id=${normalizedActivityId} url=${targetUrl}`);
    await page.goto(targetUrl);
    await page.wait(2);
    const href = stringValue(unwrapEvaluateResult(await page.evaluate('location.href')));
    activityLog(options.debug, `activity detail page state: activity_id=${normalizedActivityId} href=${href || '<empty>'}`);
    if (href.includes(`/obm-time-limit-info/${encodeURIComponent(normalizedActivityId)}`)) return;
    throw new CommandExecutionError(`SHEIN activity detail navigation failed before detail fetch: current=${href || '<empty>'}`);
}

function isBlankPageButtonFailure(error, clickText) {
    const message = String(error?.message || error);
    return message.includes(`button not found: ${clickText}`) && message.includes('current=about:blank');
}

function isCaptureTimeout(error) {
    return String(error?.message || error).includes('capture timeout');
}

async function captureFirstActivityPage(page, options) {
    const captureWithClick = async (clickText) => captureRequestViaPageTap(page, {
        pattern: ACTIVITY_LIST_API_PATTERN,
        timeoutMs: options.timeoutMs,
        targetUrl: '',
        clickText,
        label: 'SHEIN activity list first-page response',
    });
    const attempts = parsePositiveInt(options.captureAttempts, 'activity list capture attempts', 3);
    let lastError;
    for (let attempt = 1; attempt <= attempts; attempt++) {
        activityLog(options.debug, `first-page capture attempt ${attempt}/${attempts}: preparing activity page`);
        await ensureActivityPage(page, { debug: options.debug });
        try {
            activityLog(options.debug, `first-page capture attempt ${attempt}/${attempts}: click 创建记录`);
            const context = extractActivityCaptureContext(await captureWithClick('创建记录'));
            activityLog(options.debug, `first-page capture success: click=创建记录 request=${context.requestUrl}`);
            return context;
        } catch (error) {
            lastError = error;
            activityLog(options.debug, `first-page capture attempt ${attempt}/${attempts} failed: ${error?.message || error}`);
            if (isCaptureTimeout(error)) {
                activityLog(options.debug, `first-page capture attempt ${attempt}/${attempts}: fallback to 搜索 after timeout`);
                await ensureActivityPage(page, { debug: options.debug });
                try {
                    const context = extractActivityCaptureContext(await captureWithClick('搜索'));
                    activityLog(options.debug, `first-page capture success: click=搜索 request=${context.requestUrl}`);
                    return context;
                } catch (searchError) {
                    lastError = searchError;
                    activityLog(options.debug, `first-page capture fallback failed: ${searchError?.message || searchError}`);
                    if (!isBlankPageButtonFailure(searchError, '搜索') && !isCaptureTimeout(searchError)) throw searchError;
                }
            } else if (!isBlankPageButtonFailure(error, '创建记录')) {
                throw error;
            }
        }
    }
    throw lastError;
}

export async function collectSheinActivityRows(page, kwargs, debug = false) {
    const timeoutMs = parsePositiveInt(kwargs.requestTimeout, '--requestTimeout', 60) * 1000;
    activityLog(debug, `command start: snapshotDate=${stringValue(kwargs.snapshotDate) || '<default-yesterday>'} limitActivities=${stringValue(kwargs.limitActivities) || '<none>'} maxListPages=${stringValue(kwargs.maxListPages) || '<unbounded>'} maxDetailPages=${stringValue(kwargs.maxDetailPages) || '<unbounded>'} requestTimeoutMs=${timeoutMs}`);
    const firstPageContext = await captureFirstActivityPage(page, { timeoutMs, debug });
    const window = resolveActivityQueryWindow(kwargs, firstPageContext.body);
    activityLog(debug, `query window resolved: snapshotDate=${window.snapshotDate} insertStartTime=${window.insertStartTime} insertEndTime=${window.insertEndTime}`);
    const options = {
        ...window,
        debug,
        store: kwargs.store,
        profile: kwargs.profile,
        activityIds: kwargs.activityIds,
        pageSize: kwargs.pageSize === undefined || kwargs.pageSize === null || kwargs.pageSize === ''
            ? parsePositiveInt(firstPageContext.body?.page_size ?? firstPageContext.body?.pageSize, '--pageSize', 100)
            : parsePositiveInt(kwargs.pageSize, '--pageSize', 100),
        typeId: kwargs.typeId,
        system: kwargs.system,
        timeZone: kwargs.timeZone,
        limitActivities: kwargs.limitActivities === undefined || kwargs.limitActivities === null || kwargs.limitActivities === ''
            ? null
            : parsePositiveInt(kwargs.limitActivities, '--limitActivities', 1),
        limitRows: kwargs.limitRows === undefined || kwargs.limitRows === null || kwargs.limitRows === ''
            ? null
            : parsePositiveInt(kwargs.limitRows, '--limitRows', 1),
        maxListPages: kwargs.maxListPages === undefined || kwargs.maxListPages === null || kwargs.maxListPages === ''
            ? Number.MAX_SAFE_INTEGER
            : parsePositiveInt(kwargs.maxListPages, '--maxListPages', 1),
        maxDetailPages: kwargs.maxDetailPages === undefined || kwargs.maxDetailPages === null || kwargs.maxDetailPages === ''
            ? Number.MAX_SAFE_INTEGER
            : parsePositiveInt(kwargs.maxDetailPages, '--maxDetailPages', 1),
        detailConcurrency: parsePositiveInt(kwargs.detailConcurrency, '--detailConcurrency', 5),
        requestDelayMinMs: parseNonNegativeInt(kwargs.requestDelayMinMs, '--requestDelayMinMs', 0),
        requestDelayMaxMs: parseNonNegativeInt(kwargs.requestDelayMaxMs, '--requestDelayMaxMs', 500),
        timeoutMs,
        retryAttempts: parsePositiveInt(kwargs.retryAttempts, '--retryAttempts', 3),
        retryDelayMs: parseNonNegativeInt(kwargs.retryDelayMs, '--retryDelayMs', 1000),
    };
    return fetchActivityRows(page, firstPageContext, options);
}

cli({
    site: 'shein',
    name: 'activity',
    access: 'read',
    description: '拉取 SHEIN 活动列表和活动商品明细数据',
    example: 'opencli shein activity --snapshotDate 2026-07-30 --limitActivities 5 -f json',
    domain: 'sso.geiwohuo.com',
    strategy: Strategy.COOKIE,
    browser: true,
    navigateBefore: false,
    defaultWindowMode: 'foreground',
    defaultFormat: 'json',
    args: [
        { name: 'snapshotDate', help: 'raw DB 快照日期，支持 YYYY-MM-DD 或 YYYYMMDD；不传则默认昨天' },
        { name: 'insertStartTime', help: '活动列表 insert_start_time；不传沿用页面请求或 snapshotDate 往前 6 个月 00:00:00' },
        { name: 'insertEndTime', help: '活动列表 insert_end_time；不传沿用页面请求或 snapshotDate 23:59:59' },
        { name: 'activityIds', help: '只抓指定活动详情；支持逗号、换行、JSON array 或 1-2-3' },
        { name: 'typeId', help: '活动类型；不传沿用页面请求或 31' },
        { name: 'system', help: 'SHEIN system；不传沿用页面请求或 mrs' },
        { name: 'timeZone', help: 'SHEIN time_zone；不传沿用页面请求或 Asia/Shanghai' },
        { name: 'store', help: '可选店铺名，原样写入输出 store 字段' },
        { name: 'profile', help: '可选 profile 标记，原样写入输出 profile 字段' },
        { name: 'pageSize', type: 'int', help: '列表和详情接口每页数量；不传则沿用页面请求或 100' },
        { name: 'limitActivities', type: 'int', help: '最多处理活动数量，调试用' },
        { name: 'limitRows', type: 'int', help: '最多返回详情行数，调试用' },
        { name: 'maxListPages', type: 'int', help: '最多拉取活动列表页数，调试用' },
        { name: 'maxDetailPages', type: 'int', help: '每个活动最多拉取详情页数，调试用' },
        { name: 'detailConcurrency', type: 'int', default: 5, help: '详情阶段活动并发数' },
        { name: 'requestDelayMinMs', type: 'int', default: 0, help: '请求之间最小延迟毫秒' },
        { name: 'requestDelayMaxMs', type: 'int', default: 500, help: '请求之间最大延迟毫秒' },
        { name: 'timeout', type: 'int', default: 3600, help: '整条 SHEIN 活动命令总超时时间（秒）' },
        { name: 'requestTimeout', type: 'int', default: 60, help: '单个 SHEIN 页面 API 捕获/请求超时时间（秒）' },
        { name: 'retryAttempts', type: 'int', default: 3, help: '页面 API 网络/5xx 失败重试次数' },
        { name: 'retryDelayMs', type: 'int', default: 1000, help: '页面 API 重试基础间隔毫秒；会按尝试次数线性递增' },
    ],
    columns: SHEIN_ACTIVITY_COLUMNS,
    func: collectSheinActivityRows,
});

export const __test__ = {
    normalizeDateInput,
    defaultSnapshotDate,
    resolveActivityQueryWindow,
    filterReplayableHeaders,
    splitActivityIds,
    extractActivityIds,
    extractActivityCaptureContext,
    buildActivityListBody,
    buildActivityDetailBody,
    flattenActivityRows,
    fetchActivityRows,
    detailHeaders,
    buildTapCaptureJs,
    buildActivityListPageStateJs,
    ensureActivityPage,
    getRows,
    getTotalCount,
    getTotalPages,
    getKnownTotalPages,
};
