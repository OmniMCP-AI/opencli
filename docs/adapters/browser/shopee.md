# Shopee

**Mode**: 🔐 Browser · **Primary domains**: `shopee.sg`, `shopee.com.my`

OpenCLI supports Shopee product search, product detail extraction, and Shopdora review export.

## Commands

| Command | Description |
|---------|-------------|
| `opencli shopee search <query>` | Search Shopee product links and return `rank`, `product_url`, and `title`; defaults to `https://shopee.com.my` and accepts `--origin` for other Shopee regions |
| `opencli shopee product <product-url>` | Read a Shopee product page and extract visible product, pricing, seller, variant, media, and Shopdora-annotated fields |
| `opencli shopee product-shopdora-download <product-url>` | Run the Shopdora export-review workflow from a Shopee product page and wait for the downloaded CSV |

## Usage Examples

```bash
# Search Shopee product links
opencli shopee search "wireless earbuds" --origin https://shopee.sg --limit 10 -f json

# Read one Shopee product page
opencli shopee product "https://shopee.sg/...-i.123.456" -f json

# Export Shopdora review CSV for the same product
opencli shopee product-shopdora-download "https://shopee.sg/...-i.123.456" -f json
```

## Prerequisites

- Chrome running with an active Shopee session in the shared profile
- [Browser Bridge extension](/guide/browser-bridge) installed
- For `search`, sign in to the Shopee origin you plan to query if that market prompts for login
- For `product-shopdora-download`, Shopdora must already be logged in on the product page if you want the export to succeed
- For `product-shopdora-download`, your Browser Bridge build must support download tracking

## Notes

- `search` defaults to `https://shopee.com.my`; use `--origin https://shopee.sg` or another Shopee host to search a different region.
- `product` returns page-visible Shopee fields even if Shopdora is not logged in. In that case `shopdora_login_message` will be populated.
- `product-shopdora-download` opens the export dialog, shifts the time-period start date from the current value by `-3 months + 7 days`, enables the review-image detail filter when available, and waits for the CSV download to finish.
- The download command has a long timeout because Shopdora export generation can be slow.
- Output fields for the download flow include `status`, `message`, `local_url`, `local_path`, `product_url`, and `shopdora_login_message`.

## Troubleshooting

- If `search` returns `Shopee login required`, open the same Shopee origin in Chrome, complete login, and retry.
- If you get `Shopdora 未登录`, log into Shopdora on the real Shopee product page in Chrome and retry.
- If the download command says download tracking is unavailable, reload or upgrade the Browser Bridge extension.
- If the wrong tab is active, retry after opening the target Shopee product page directly in Chrome.
