import { describe, expect, it } from 'vitest';
import { __test__, SHEIN_ACTIVITY_COLUMNS } from './activity.js';

describe('shein activity adapter', () => {
    it('resolves snapshot dates and default insert windows', () => {
        expect(__test__.normalizeDateInput('20260730', '--snapshotDate')).toBe('2026-07-30');
        expect(__test__.defaultSnapshotDate(new Date('2026-07-30T10:00:00+08:00'))).toBe('2026-07-29');

        expect(__test__.resolveActivityQueryWindow({
            snapshotDate: '2026-07-30',
        }, {})).toEqual({
            snapshotDate: '2026-07-30',
            insertStartTime: '2026-01-30 00:00:00',
            insertEndTime: '2026-07-30 23:59:59',
        });

        expect(__test__.resolveActivityQueryWindow({
            snapshotDate: '2026-07-30',
        }, {
            insert_start_time: '2026-06-01 00:00:00',
            insert_end_time: '2026-06-30 23:59:59',
        })).toEqual({
            snapshotDate: '2026-07-30',
            insertStartTime: '2026-06-01 00:00:00',
            insertEndTime: '2026-06-30 23:59:59',
        });

        expect(__test__.resolveActivityQueryWindow({
            snapshotDate: '2026-08-31',
        }, {})).toEqual({
            snapshotDate: '2026-08-31',
            insertStartTime: '2026-02-28 00:00:00',
            insertEndTime: '2026-08-31 23:59:59',
        });
    });

    it('sanitizes replay headers while preserving SHEIN business headers', () => {
        const headers = __test__.filterReplayableHeaders({
            Cookie: 'secret=1',
            Host: 'sso.geiwohuo.com',
            'Content-Length': '42',
            Origin: 'https://sso.geiwohuo.com',
            Referer: 'https://sso.geiwohuo.com/#/mars/tools/list',
            'Sec-Fetch-Site': 'same-origin',
            Priority: 'u=1',
            'Proxy-Connection': 'keep-alive',
            Accept: 'application/json',
            'Origin-Url': 'https://sso.geiwohuo.com/#/mrs/tools/activity/obm-time-limit-info/101',
            'X-Bbl-Route': '/mrs/tools/activity/obm-time-limit-info/101',
            'X-Req-Zone-Id': 'CN',
            'X-Req-Sso-Zone-Id': 'CN',
            Lan: 'zh-cn',
            'X-Lt-Language': 'zh-cn',
            'Anti-Content': 'business-check',
        });

        expect(headers).toEqual({
            accept: 'application/json',
            'origin-url': 'https://sso.geiwohuo.com/#/mrs/tools/activity/obm-time-limit-info/101',
            'x-bbl-route': '/mrs/tools/activity/obm-time-limit-info/101',
            'x-req-zone-id': 'CN',
            'x-req-sso-zone-id': 'CN',
            lan: 'zh-cn',
            'x-lt-language': 'zh-cn',
            'anti-content': 'business-check',
        });
    });

    it('builds activity list capture script around 创建记录 instead of 搜索', () => {
        const script = __test__.buildTapCaptureJs({
            pattern: '/query_obm_activity_list',
            timeoutMs: 120000,
            clickText: '创建记录',
        });

        expect(script).toContain('创建记录');
        expect(script).toContain('candidateScore');
        expect(script).not.toContain("includes('搜索')");
    });

    it('builds activity detail headers like the legacy crawler route context', () => {
        const headers = __test__.detailHeaders({
            accept: 'application/json',
            lan: 'zh-cn',
            'x-lt-language': 'zh-cn',
        }, '101');

        expect(headers).toMatchObject({
            accept: 'application/json',
            'origin-url': 'https://sso.geiwohuo.com/#/mrs/tools/activity/obm-time-limit-info/101',
            'x-bbl-route': '/mrs/tools/activity/obm-time-limit-info/101',
            lan: 'CN',
            'x-lt-language': 'CN',
        });
        expect(headers['x-req-zone-id']).toBeTruthy();
        expect(headers['x-req-sso-zone-id']).toBeTruthy();
    });

    it('retries activity list navigation until 创建记录 is visible', async () => {
        const states = [
            { href: 'about:blank', hasCreateRecord: false, hasSearchButton: false, availableTexts: [] },
            { href: 'https://sso.geiwohuo.com/#/mars/tools/list', hasCreateRecord: true, hasSearchButton: false, availableTexts: ['营销工具创建记录托管记录'] },
        ];
        const page = {
            gotoCalls: [],
            goto: async (url, options) => { page.gotoCalls.push([url, options]); },
            wait: async () => {},
            evaluate: async () => states.shift(),
        };

        await expect(__test__.ensureActivityPage(page, { attempts: 2 })).resolves.toMatchObject({
            href: 'https://sso.geiwohuo.com/#/mars/tools/list',
            hasCreateRecord: true,
            hasSearchButton: false,
        });
        expect(page.gotoCalls).toEqual([
            ['https://sso.geiwohuo.com/#/mars/tools/list', { waitUntil: 'none' }],
            ['https://sso.geiwohuo.com/#/mars/tools/list', { waitUntil: 'none' }],
        ]);
    });

    it('fails activity list navigation when 创建记录 never appears', async () => {
        const page = {
            goto: async () => {},
            wait: async () => {},
            evaluate: async () => ({
                href: 'https://sso.geiwohuo.com/#/mars/tools/list',
                hasCreateRecord: false,
                hasSearchButton: false,
                availableTexts: ['搜索', '导出'],
            }),
        };

        await expect(__test__.ensureActivityPage(page, { attempts: 1 })).rejects.toThrow(
            'SHEIN activity list page not ready before API fetch: current=https://sso.geiwohuo.com/#/mars/tools/list available=搜索 | 导出',
        );
    });

    it('detects 创建记录 in the activity list page state script', () => {
        const script = __test__.buildActivityListPageStateJs();

        expect(script).toContain('hasCreateRecord');
        expect(script).toContain('hasSearchButton');
        expect(script).toContain('创建记录');
    });

    it('splits activity ids from cli strings and list rows', () => {
        expect(__test__.splitActivityIds('101, 102\n103')).toEqual(['101', '102', '103']);
        expect(__test__.splitActivityIds('["201","202",203]')).toEqual(['201', '202', '203']);
        expect(__test__.splitActivityIds('301-302-301')).toEqual(['301', '302']);
        expect(__test__.extractActivityIds([
            { activity_id: '401' },
            { prom_id: 402 },
            { id: '403' },
            { activityId: '401' },
        ])).toEqual(['401', '402', '403']);
    });

    it('builds list and detail payloads from captured filters and overrides', () => {
        expect(__test__.buildActivityListBody({
            insert_start_time: 'captured-start',
            insert_end_time: 'captured-end',
            page_num: 9,
            page_size: 20,
            type_id: 9,
            system: 'captured-system',
            time_zone: 'Captured/Zone',
            keep_me: true,
        }, 2, {
            snapshotDate: '2026-07-30',
            insertStartTime: '2026-01-30 00:00:00',
            insertEndTime: '2026-07-30 23:59:59',
            pageSize: 50,
            typeId: 31,
            system: 'mrs',
            timeZone: 'Asia/Shanghai',
        })).toEqual({
            insert_start_time: '2026-01-30 00:00:00',
            insert_end_time: '2026-07-30 23:59:59',
            page_num: 2,
            page_size: 50,
            type_id: 31,
            system: 'mrs',
            time_zone: 'Asia/Shanghai',
            keep_me: true,
        });

        expect(__test__.buildActivityDetailBody('101', 3, { pageSize: 25 })).toEqual({
            activity_id: '101',
            page_num: 3,
            page_size: 25,
        });
    });

    it('reads legacy response shapes with records and page counts', () => {
        const payload = {
            result: {
                data: {
                    records: [{ activity_id: '101' }],
                    total_count: 1,
                    page_count: 3,
                },
            },
        };

        expect(__test__.getRows(payload)).toEqual([{ activity_id: '101' }]);
        expect(__test__.getTotalCount(payload, 0)).toBe(1);
        expect(__test__.getTotalPages(payload, 100, 1)).toBe(3);
        expect(__test__.getKnownTotalPages(payload, 100)).toBe(3);
    });

    it('flattens activity detail rows and preserves list-only raw snapshots', () => {
        const activity = {
            activity_id: 101,
            activity_name: 'Summer',
            type_id: 31,
            start_time: '2026-07-01 00:00:00',
            end_time: '2026-07-31 23:59:59',
            terminate_time: '',
            state: 3,
        };
        const detail = {
            goods_id: 'g-1',
            skc: 'skc-1',
            image_url: '//img.ltwebstatic.com/skc.jpg',
            sku_supplier_no: 'supplier-1',
            sku_info_list: [{ sku: 'sku-1', sku_product_act_price: '9.99', attr_value_name: 'Red' }],
        };

        const detailRows = __test__.flattenActivityRows(activity, [detail], {
            snapshotDate: '2026-07-30',
            store: '店1',
            profile: 'profile1',
            listRequestUrl: 'https://sso.geiwohuo.com/mrs-api-prefix/promotion/obm/query_obm_activity_list',
            detailRequestUrl: 'https://sso.geiwohuo.com/mrs-api-prefix/promotion/simple_platform/query_goods_detail',
            activityPageNum: 1,
            detailPageNum: 1,
            activityTotalCount: 1,
            detailTotalCount: 1,
        });

        expect(detailRows[0]).toMatchObject({
            record_type: 'activity_detail',
            snapshot_date: '2026-07-30',
            store: '店1',
            profile: 'profile1',
            activity_id: '101',
            activity_name: 'Summer',
            activity_type_id: 31,
            type_id: 31,
            state: 3,
            skc: 'skc-1',
            image_url: 'https://img.ltwebstatic.com/skc.jpg',
            sku_supplier_no: 'supplier-1',
            sku: 'sku-1',
            raw_activity_json: activity,
            raw_detail_json: detail,
            raw_json: detail,
        });
        expect(Object.keys(detailRows[0])).toEqual(SHEIN_ACTIVITY_COLUMNS);

        const listOnly = __test__.flattenActivityRows(activity, [], {
            snapshotDate: '2026-07-30',
            store: '店1',
            profile: 'profile1',
        });
        expect(listOnly).toHaveLength(1);
        expect(listOnly[0]).toMatchObject({
            record_type: 'activity_list_only',
            activity_id: '101',
            skc: '',
            raw_activity_json: activity,
            raw_detail_json: {},
            raw_json: activity,
        });
    });

    it('collects list and detail pages with bounded detail concurrency', async () => {
        const inFlight = { current: 0, max: 0 };
        const fetchedBodies = [];
        const page = {
            href: '',
            goto: async (url) => { page.href = url; },
            evaluate: async () => page.href,
            fetchJson: async (url, options) => {
                fetchedBodies.push({ url, body: options.body });
                if (url.includes('query_obm_activity_list')) {
                    return {
                        code: 0,
                        info: {
                            list: options.body.page_num === 1
                                ? [{ activity_id: 'a1', activity_name: 'A1' }, { activity_id: 'a2', activity_name: 'A2' }]
                                : [],
                            total: 2,
                        },
                    };
                }
                inFlight.current += 1;
                inFlight.max = Math.max(inFlight.max, inFlight.current);
                await new Promise((resolve) => setTimeout(resolve, 5));
                inFlight.current -= 1;
                return {
                    code: 0,
                    info: {
                        list: [{ skc: `skc-${options.body.activity_id}`, sku_supplier_no: `supplier-${options.body.activity_id}` }],
                        total: 1,
                    },
                };
            },
            wait: async () => {},
        };

        const rows = await __test__.fetchActivityRows(page, {
            headers: {},
            body: { page_size: 2, type_id: 31, system: 'mrs' },
            response: { code: 0, info: { list: [], total: 2 } },
            requestUrl: 'https://sso.geiwohuo.com/mrs-api-prefix/promotion/obm/query_obm_activity_list',
        }, {
            snapshotDate: '2026-07-30',
            store: '店1',
            profile: 'profile1',
            pageSize: 2,
            maxListPages: 3,
            maxDetailPages: 1,
            detailConcurrency: 2,
            limitActivities: 2,
            limitRows: null,
            requestDelayMinMs: 0,
            requestDelayMaxMs: 0,
            timeoutMs: 60000,
            retryAttempts: 1,
            retryDelayMs: 0,
        });

        expect(rows.map((row) => row.skc)).toEqual(['skc-a1', 'skc-a2']);
        expect(inFlight.max).toBeLessThanOrEqual(2);
        expect(page.href).toBe('https://sso.geiwohuo.com/#/mrs/tools/activity/obm-time-limit-info/a1');
        expect(fetchedBodies.filter((item) => item.url.includes('query_obm_activity_list')).map((item) => item.body.page_num)).toEqual([1]);
        expect(fetchedBodies.filter((item) => item.url.includes('query_goods_detail')).map((item) => item.body.activity_id).sort()).toEqual(['a1', 'a2']);
    });

    it('collects paginated legacy records response shapes', async () => {
        const fetchedBodies = [];
        const page = {
            href: '',
            goto: async (url) => { page.href = url; },
            evaluate: async () => page.href,
            fetchJson: async (url, options) => {
                fetchedBodies.push({ url, body: options.body });
                if (url.includes('query_obm_activity_list')) {
                    return {
                        result: {
                            data: {
                                records: options.body.page_num === 1
                                    ? [{ activity_id: 'a1', activity_name: 'A1' }]
                                    : [{ activity_id: 'a2', activity_name: 'A2' }],
                                total_count: 2,
                                page_count: 2,
                            },
                        },
                    };
                }
                return {
                    result: {
                        data: {
                            records: [{ skc: `skc-${options.body.activity_id}` }],
                            total_count: 1,
                            page_count: 1,
                        },
                    },
                };
            },
            wait: async () => {},
        };

        const rows = await __test__.fetchActivityRows(page, {
            headers: {},
            body: { page_size: 1 },
            requestUrl: 'https://sso.geiwohuo.com/mrs-api-prefix/promotion/obm/query_obm_activity_list',
        }, {
            snapshotDate: '2026-07-30',
            store: '店1',
            profile: 'profile1',
            pageSize: 1,
            maxListPages: 3,
            maxDetailPages: 1,
            detailConcurrency: 1,
            limitActivities: null,
            limitRows: null,
            requestDelayMinMs: 0,
            requestDelayMaxMs: 0,
            timeoutMs: 60000,
            retryAttempts: 1,
            retryDelayMs: 0,
        });

        expect(rows.map((row) => row.skc)).toEqual(['skc-a1', 'skc-a2']);
        expect(fetchedBodies.filter((item) => item.url.includes('query_obm_activity_list')).map((item) => item.body.page_num)).toEqual([1, 2]);
    });

    it('continues full pages until a short page when totals are missing', async () => {
        const fetchedBodies = [];
        const page = {
            href: '',
            goto: async (url) => { page.href = url; },
            evaluate: async () => page.href,
            fetchJson: async (url, options) => {
                fetchedBodies.push({ url, body: options.body });
                if (url.includes('query_obm_activity_list')) {
                    return {
                        data: {
                            records: options.body.page_num === 1
                                ? [{ activity_id: 'a1' }]
                                : [{ activity_id: 'a2' }],
                        },
                    };
                }
                return {
                    data: {
                        records: options.body.activity_id === 'a1' && options.body.page_num === 1
                            ? [{ skc: 'skc-a1' }]
                            : [],
                    },
                };
            },
            wait: async () => {},
        };

        const rows = await __test__.fetchActivityRows(page, {
            headers: {},
            body: { page_size: 1 },
            requestUrl: 'https://sso.geiwohuo.com/mrs-api-prefix/promotion/obm/query_obm_activity_list',
        }, {
            snapshotDate: '2026-07-30',
            store: '店1',
            profile: 'profile1',
            pageSize: 1,
            maxListPages: 2,
            maxDetailPages: 2,
            detailConcurrency: 1,
            limitActivities: null,
            limitRows: null,
            requestDelayMinMs: 0,
            requestDelayMaxMs: 0,
            timeoutMs: 60000,
            retryAttempts: 1,
            retryDelayMs: 0,
        });

        expect(rows.map((row) => [row.activity_id, row.skc])).toEqual([
            ['a1', 'skc-a1'],
            ['a2', ''],
        ]);
        expect(fetchedBodies.filter((item) => item.url.includes('query_obm_activity_list')).map((item) => item.body.page_num)).toEqual([1, 2]);
        expect(fetchedBodies.filter((item) => item.url.includes('query_goods_detail') && item.body.activity_id === 'a1').map((item) => item.body.page_num)).toEqual([1, 2]);
    });
});
