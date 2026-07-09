import { describe, expect, it } from 'vitest';
import { __test__ } from './aftersales.js';

describe('shein aftersales adapter', () => {
    it('flattens list goods and matches return attachments per goods item', () => {
        const rows = __test__.flattenSheinAftersalesOrder({
            id: '235271063',
            aftersalesOrderNo: 'AC2607062532847616',
            returnOrderNo: '183QC0QWDL',
            orderNo: 'GSH18U09700UNAC',
            site: 'shein-jp',
            orderSubStatusName: '待买家退货',
            aftersalesResolutionPlanName: '退货退款',
            requestTime: '2026-07-06 11:44:08',
            afterSalesReasonList: [{ reasonName: '发错退回' }],
            afterSalesStatusGuide: { etaTime: '2026-07-09 15:48:31' },
            afterSalesOrderGoodsInfos: [
                {
                    goodsId: 293199253,
                    entityId: 2383363172116501,
                    goodsTitle: 'cart 1',
                    goodsSn: '251219-黑白收纳桌',
                    skuSn: 'ZWJ-black',
                    suffix: 'Black(黑色)-1PC',
                    quantity: 1,
                    priceAmount: 2280,
                    checkEstimateIncomeMoney: 2000,
                    returnExpense: 0,
                    performancePrice: 571,
                    freezeAmount: 0,
                },
                {
                    goodsId: 293199254,
                    entityId: 2383363172116502,
                    goodsTitle: 'cart 2',
                    goodsSn: '251219-黑白收纳桌',
                    skuSn: 'ZWJ-black*2',
                    suffix: 'Black(黑色)-2pcs',
                    quantity: 1,
                    priceAmount: 4380,
                    checkEstimateIncomeMoney: 3664,
                    returnExpense: 0,
                    performancePrice: 1141,
                    freezeAmount: 0,
                },
            ],
        }, {
            buyerInstruction: 'Please check package parts',
            returnExpressInfoList: [
                { expressNo: 'EXP001' },
                { expressNo: 'EXP002' },
                { expressNo: 'EXP001' },
            ],
            goodsInfo: {
                goodsList: [
                    {
                        id: 293199253,
                        entityId: 2383363172116501,
                        skuSn: 'ZWJ-black',
                        suffix: 'Black(黑色)-1PC',
                        images: ['//img.shein.com/a.jpg'],
                        videos: [],
                        promotionAmount: 280,
                        refundRatio: 88.5,
                        estimateIncomeMoney: 2571,
                        goodsSettlePrice: 2000,
                        goodsServiceCharge: 427,
                    },
                    {
                        id: 293199254,
                        entityId: 2383363172116502,
                        skuSn: 'ZWJ-black*2',
                        suffix: 'Black(黑色)-2pcs',
                        images: ['//img.shein.com/b.jpg'],
                        videos: ['https://video.ltwebstatic.com/b.mp4'],
                        promotionAmount: 716,
                        refundRatio: 83.65,
                        estimateIncomeMoney: 4805,
                        goodsSettlePrice: 3664,
                        goodsServiceCharge: 820,
                    },
                ],
            },
        });

        expect(rows).toHaveLength(2);
        expect(rows[0]).toMatchObject({
            aftersalesOrderNo: 'AC2607062532847616',
            etaTime: '2026-07-09 15:48:31',
            goodsTitle: 'cart 1',
            refundMethod: '退货退款',
            afterSalesReason: ['发错退回'],
            buyerInstruction: 'Please check package parts',
            returnExpressNos: ['EXP001', 'EXP002'],
            return_attachments: ['https://img.shein.com/a.jpg'],
        });
        expect(rows[1]).toMatchObject({
            goodsTitle: 'cart 2',
            return_attachments: ['https://img.shein.com/b.jpg', 'https://video.ltwebstatic.com/b.mp4'],
            performancePrice: 1141,
            promotionAmount: 716,
            refundRatio: 83.65,
            estimateIncomeMoney: 4805,
            goodsSettlePrice: 3664,
            goodsServiceCharge: 820,
        });
    });

    it('uses evidence buyerImages when there is no return order number', () => {
        const rows = __test__.flattenSheinAftersalesOrder({
            aftersalesOrderNo: 'AC2607073444048896',
            returnOrderNo: '',
            afterSalesOrderGoodsInfos: [{ goodsTitle: 'rack', quantity: 1 }],
        }, {
            buyerInstruction: 'No return order instruction',
            reasons: ['发错退回'],
            buyerImages: ['//img.shein.com/evidence.jpg'],
        });

        expect(rows).toHaveLength(1);
        expect(rows[0].return_attachments).toEqual(['https://img.shein.com/evidence.jpg']);
        expect(rows[0].afterSalesReason).toEqual(['发错退回']);
        expect(rows[0].buyerInstruction).toEqual('No return order instruction');
    });

    it('derives refund method from resolution plan and refund ratio', () => {
        const partialRows = __test__.flattenSheinAftersalesOrder({
            aftersalesResolutionPlanName: '仅退款',
            afterSalesOrderGoodsInfos: [{ goodsTitle: 'rack', quantity: 1 }],
        }, {
            goodsInfo: { goodsList: [{ refundRatio: 30 }] },
        });
        expect(partialRows[0].refundMethod).toEqual('仅退款30%');

        const defaultRows = __test__.flattenSheinAftersalesOrder({
            aftersalesResolutionPlanName: '仅退款',
            afterSalesOrderGoodsInfos: [{ goodsTitle: 'rack', quantity: 1 }],
        }, {});
        expect(defaultRows[0].refundMethod).toEqual('仅退款100%');

        const otherRows = __test__.flattenSheinAftersalesOrder({
            aftersalesResolutionPlanName: '驳回售后',
            afterSalesOrderGoodsInfos: [{ goodsTitle: 'rack', quantity: 1 }],
        }, {});
        expect(otherRows[0].refundMethod).toEqual('');
    });

    it('extracts reusable list pagination context from a captured first-page request', () => {
        const context = __test__.extractListCaptureContext([
            {
                url: '/gsp/aftersalesOrder/list',
                requestHeaders: {
                    Accept: '*/*',
                    'Build-Version': '2026-07-07 17:45',
                    'Content-Type': 'application/json;Charset=utf-8',
                    Cookie: 'secret=1',
                    'X-Log-VisitorId': '_n-OBFckyOByISQY_GJV5',
                },
                requestBodyPreview: '{"quickType":0,"page":1,"perPage":50}',
                responsePreview: '{"code":0,"info":{"data":[{"id":"1"}],"total":80}}',
                responseStatus: 200,
            },
        ]);

        expect(context).toMatchObject({
            headers: {
                accept: '*/*',
                'build-version': '2026-07-07 17:45',
                'content-type': 'application/json;Charset=utf-8',
                'x-log-visitorid': '_n-OBFckyOByISQY_GJV5',
            },
            body: {
                quickType: 0,
                page: 1,
                perPage: 50,
            },
        });
        expect(context.headers).not.toHaveProperty('cookie');
        expect(context.response.info.data).toHaveLength(1);
    });

    it('matches detail capture entries by aftersalesOrderId request body', () => {
        const detail = __test__.extractDetailFromCapture([
            {
                url: '/gsp/aftersalesOrder/detail',
                requestBodyPreview: '{"aftersalesOrderId":"wrong"}',
                responsePreview: '{"code":0,"info":{"buyerInstruction":"skip"}}',
                responseStatus: 200,
            },
            {
                url: '/gsp/aftersalesOrder/detail',
                requestBodyPreview: '{"aftersalesOrderId":"235271063"}',
                responsePreview: '{"code":0,"info":{"buyerInstruction":"hit"}}',
                responseStatus: 200,
            },
        ], '235271063');

        expect(detail.info.buyerInstruction).toBe('hit');
    });

    it('builds subsequent page payloads by copying page-1 request and overriding page', () => {
        const payload = __test__.buildPaginatedListBody({
            quickType: 0,
            page: 1,
            perPage: 50,
            keyword: 'keep',
        }, 3, 20);

        expect(payload).toEqual({
            quickType: 0,
            page: 3,
            perPage: 20,
            keyword: 'keep',
        });
    });

    it('uses randomized delay bounds between 2 and 4 seconds', () => {
        expect(__test__.randomDelayMs(() => 0)).toBe(2000);
        expect(__test__.randomDelayMs(() => 0.9999)).toBe(4000);
    });
});
