import { describe, expect, it } from 'vitest';
import { __test__ } from './auth.js';

describe('shein auth adapter', () => {
  it('builds a browser-context GSP auth probe', () => {
    const script = __test__.buildVerifyScript();

    expect(script).toContain('https://sso.geiwohuo.com/gsp/aftersalesOrder/list');
    expect(script).toContain("credentials: 'include'");
    expect(script).toContain('quickType: 0');
    expect(script).toContain('perPage: 1');
  });

  it('parses cookie values used for identity summary', () => {
    const cookie = 'foo=bar; gsp_store_site=shein-jp; SITE_ID=05c6226e-dc9c-4969-869d-1a00665bf10a';

    expect(__test__.parseCookieValue(cookie, 'gsp_store_site')).toBe('shein-jp');
    expect(__test__.parseCookieValue(cookie, 'SITE_ID')).toBe('05c6226e-dc9c-4969-869d-1a00665bf10a');
    expect(__test__.parseCookieValue(cookie, 'missing')).toBe('');
  });
});
