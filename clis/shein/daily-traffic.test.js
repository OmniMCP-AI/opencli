import { describe, expect, it } from 'vitest';
import { __test__, SHEIN_DAILY_TRAFFIC_COLUMNS } from './daily-traffic.js';

describe('shein daily traffic adapter', () => {
    it('normalizes daily date ranges from compact and reversed inputs', () => {
        expect(__test__.normalizeDateInput('2026-7-8', '--startDate')).toBe('2026-07-08');
        expect(__test__.normalizeDateInput('20260709', '--endDate')).toBe('2026-07-09');
        expect(__test__.resolveDateRange({ startDate: '20260710' }, new Date('2026-07-29T08:00:00Z'))).toEqual(['2026-07-10']);
        expect(__test__.resolveDateRange({ endDate: '20260711' }, new Date('2026-07-29T08:00:00Z'))).toEqual(['2026-07-11']);
        expect(__test__.resolveDateRange({ startDate: '2026-07-12', endDate: '2026-07-10' })).toEqual([
            '2026-07-10',
            '2026-07-11',
            '2026-07-12',
        ]);
    });

    it('normalizes countrySite values from CLI and captured request bodies', () => {
        expect(__test__.normalizeCountrySite('shein-jp, shein-us', ['captured'])).toEqual(['shein-jp', 'shein-us']);
        expect(__test__.normalizeCountrySite('', ['shein-de'])).toEqual(['shein-de']);
        expect(__test__.normalizeCountrySite(undefined, 'shein-fr')).toEqual(['shein-fr']);
        expect(__test__.normalizeCountrySite(undefined, [])).toEqual(['shein-all']);
    });

    it('sanitizes replay headers with the SHEIN allowlist', () => {
        const headers = __test__.filterReplayableHeaders({
            Accept: '*/*',
            Cookie: 'secret=1',
            Host: 'sso.geiwohuo.com',
            'Content-Length': '42',
            Origin: 'https://sso.geiwohuo.com',
            Referer: 'https://sso.geiwohuo.com/#/sbn/merchandise/details',
            'Sec-Fetch-Site': 'same-origin',
            'Build-Version': '2026-07-29',
            'X-Log-VisitorId': 'visitor',
            'Anti-Content': 'business-check',
            'Sm-Device-Id': 'device',
        });

        expect(headers).toEqual({
            accept: '*/*',
            'build-version': '2026-07-29',
            'x-log-visitorid': 'visitor',
            'anti-content': 'business-check',
            'sm-device-id': 'device',
        });
    });

    it('extracts the traffic capture context and rejects non-zero API codes', () => {
        const context = __test__.extractTrafficCaptureContext([
            {
                url: '/sbn/new_goods/get_skc_diagnose_list',
                requestHeaders: { Accept: 'application/json', Cookie: 'secret=1' },
                requestBodyPreview: '{"areaCd":"jp","countrySite":["shein-jp"],"pageNum":1,"pageSize":20}',
                responseStatus: 200,
                responsePreview: '{"code":0,"info":{"data":[{"skc":"skc-1"}],"meta":{"count":1}}}',
            },
        ]);

        expect(context.headers).toEqual({ accept: 'application/json' });
        expect(context.body).toMatchObject({ areaCd: 'jp', countrySite: ['shein-jp'], pageNum: 1, pageSize: 20 });
        expect(context.response.info.data).toHaveLength(1);
        expect(() => __test__.extractTrafficCaptureContext([
            {
                url: '/sbn/new_goods/get_skc_diagnose_list',
                requestBodyPreview: '{}',
                responseStatus: 200,
                responsePreview: '{"code":20302,"msg":"登录失效"}',
            },
        ])).toThrow(/code=20302/);
    });

    it('builds daily request bodies while preserving captured filters', () => {
        const body = __test__.buildDailyTrafficBody(
            { areaCd: 'cn', countrySite: ['captured'], keyword: 'rack', pageNum: 9, pageSize: 20 },
            2,
            '2026-07-08',
            { areaCd: 'jp', countrySite: 'shein-jp,shein-us', pageSize: 50 },
        );

        expect(body).toEqual({
            areaCd: 'jp',
            countrySite: ['shein-jp', 'shein-us'],
            keyword: 'rack',
            dt: '20260708',
            startDate: '20260708',
            endDate: '20260708',
            pageNum: 2,
            pageSize: 50,
        });
    });

    it('flattens SHEIN daily traffic rows while preserving raw payload for DB storage', () => {
        const rawPayload = {
            goodsName: 'Kitchen Rack',
            imgUrl: '//img.ltwebstatic.com/rack.jpg',
            spu: 'spu-1',
            skc: 'skc-1',
            skuSupplierNo: 'supplier-sku',
            newGoodsTag: 1,
            layerNm: 'A',
            onsaleFlag: 1,
            saleFlag: 0,
            multicolorFlag: true,
            goodsUvIdx: 12,
            epsUvIdx: 24,
            bounceUvIdx: 3,
            bounceRate: '12.5%',
            searchClickCnt: 4,
            likeCnt: 5,
            cartUvIdx: 6,
            cartPvIdx: 7,
            gdsCartCtrIdx: '25%',
            payUvIdx: 8,
            payOrderCnt: '',
            gmv: '99.90',
            gdsPayCtrIdx: '33%',
            saleUvIdx: 9,
            saleCnt: 10,
            saleGmv: '88.80',
            gdsSaleCtrIdx: '44%',
            confirmCtrIdx: '55%',
            totalQualityLevel: 'good',
            totalCommentCnt: 11,
            payBadCommentCnt: 4,
            badCommentRate: '1%',
            returnOrderCnt: 2,
            returnQty: 3,
            newCate1Nm: 'Home',
            newCate2Nm: 'Kitchen',
            newCate3Nm: 'Storage',
            newCate4Nm: 'Rack',
            brand: 'Brand',
            listName: 'Top',
            listType: 'traffic',
            listRank: 1,
            promCampaign: {
                promTag: '促销',
                promInfIng: [{ promNm: '活动A', promId: 100 }, { promNm: '活动B', promId: 200 }],
                rightCampaign: [{ id: 1 }],
            },
        };
        const row = __test__.flattenDailyTrafficRow(rawPayload, { date: '2026-07-08', totalCount: 99, pageNum: 2, requestUrl: 'https://sso.geiwohuo.com/sbn/new_goods/get_skc_diagnose_list' });

        expect(row).toMatchObject({
            date: '2026-07-08',
            queried_start_date: '20260708',
            queried_end_date: '20260708',
            total_count: 99,
            page_num: 2,
            goods_name: 'Kitchen Rack',
            img_url: 'https://img.ltwebstatic.com/rack.jpg',
            spu: 'spu-1',
            skc: 'skc-1',
            sku_supplier_no: 'supplier-sku',
            bad_comment_cnt: 4,
            prom_tag: '促销',
            prom_names: '活动A | 活动B',
            prom_ids: '100 | 200',
            prom_inf_ing_json: [{ promNm: '活动A', promId: 100 }, { promNm: '活动B', promId: 200 }],
            right_campaign_json: [{ id: 1 }],
            raw_json: rawPayload,
        });
        expect(Object.keys(row)).toEqual(SHEIN_DAILY_TRAFFIC_COLUMNS);
    });

    it('collects paginated daily rows until total count, max pages, and limit are reached', async () => {
        const fetchedBodies = [];
        const page = {
            fetchJson: async (_url, options) => {
                fetchedBodies.push(options.body);
                const pageNum = options.body.pageNum;
                return {
                    code: 0,
                    info: {
                        data: pageNum === 1 ? [{ skc: 'a' }, { skc: 'b' }] : [{ skc: 'c' }, { skc: 'd' }],
                        meta: { count: 4 },
                    },
                };
            },
            wait: async () => {},
        };

        const rows = await __test__.fetchDailyTrafficRowsForDate(page, {
            headers: {},
            body: { areaCd: 'cn', countrySite: ['shein-all'], pageSize: 2 },
            response: { code: 0, info: { data: [], meta: { count: 4 } } },
            requestUrl: 'https://sso.geiwohuo.com/sbn/new_goods/get_skc_diagnose_list',
        }, '2026-07-08', {
            areaCd: undefined,
            countrySite: undefined,
            pageSize: 2,
            maxPages: 5,
            limitRemaining: 3,
            timeoutMs: 60000,
            retryAttempts: 1,
            retryDelayMs: 0,
        });

        expect(rows.map((row) => row.skc)).toEqual(['a', 'b', 'c']);
        expect(fetchedBodies.map((body) => body.pageNum)).toEqual([1, 2]);
    });
});
