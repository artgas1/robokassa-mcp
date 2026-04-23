# Partner API — coverage notes

Partner API is a separate Robokassa surface for integrators (CPA networks,
SaaS platforms onboarding shops, payout aggregators). It sits at
`https://services.robokassa.ru/PartnerRegisterService/api/` and uses
partner-level credentials distinct from the merchant Password#1/2/3.

Official docs: https://docs.robokassa.ru/partner-api/

## What we've implemented

| Method | Path | Module |
|---|---|---|
| RefundOperation | `POST /Operation/RefundOperation` | `robokassa.partner.partner_refund` |

## What the Partner API covers (based on service overview)

From https://docs.robokassa.ru/partner-api/ :

> Набор программных интерфейсов для взаимодействия Партнёра или Клиента сервиса
> ROBOKASSA с основным функционалом Личного кабинета Клиента.

Features enumerated:

1. **Мгновенная подача заявки на регистрацию Личного кабинета** — register a
   new merchant client (legal entity / individual entrepreneur, RU / KZ).
2. **Автоматическое создание преднастроенного магазина в кабинете клиента** —
   provision a shop under the new client.
3. **Автоматическое подключение фискализации** — enable 54-ФЗ fiscalization.
4. **Удалённое управление расчётными счетами Клиента** — manage bank accounts.
5. **Автоматическое формирование заявок на вывод денежных средств** — payouts.
6. **Автоматическое формирование заявок на проведение возвратов** — refunds
   (implemented as `partner_refund`).

## Known request-shape conventions

From https://docs.robokassa.ru/partner-api/ParametersDescription/ :

- Request bodies are JSON.
- Client registration uses a detailed schema covering: `PartnerId`, `CompanyName`,
  `ShortCompanyName`, `Email`, `ContactPerson`, `ContactPersonGenitif`, `SiteUrl`,
  `OkvedCodes`, `Phone`, `INN`, `KPP` (ЮЛ only), `OGRN`, `Account`, `BIK`,
  `ShopName`, `ShopUrl`, `ShopResultURL`, `ShopSuccessUrl`, `ShopFailUrl`,
  `SignerName`, `SignerPosition`, `SignerConfirmDoc*`, `SignerDocumentType`,
  `EgrRecordDate`, `PromoCode`, `RegAuthority`, `RegAuthorityAddress`,
  nested `LegalInfo` (director), nested `Beneficials`, address blocks
  (`Address`, `AddressReal`), `Individinfo` (ИП only), `OgrnCertificate`,
  `Passport`, `RegistrationAddress`, `Contacts` (General / Financial / Technical).

## What's NOT implemented yet

The specific HTTP paths for the other six feature groups are not listed on
the public `MethodDescription/` index (the URLs 404 when crawled via Exa in
April 2026). Likely endpoints inferred from the service purpose:

- `POST /Client/Register` — merchant registration
- `POST /Shop/Create` — provision a preconfigured shop
- `POST /Shop/EnableFiscalization` — turn on 54-ФЗ
- `POST /Account/Manage` — add / remove bank accounts
- `POST /Payout/Create` — withdraw funds to a client account

These are placeholders — do not assume the exact paths without verifying
against authoritative docs or network traces. Partners who have access to
Robokassa's full Partner API documentation (typically available after
signing a partner agreement) are best positioned to contribute these.

## Contributing

If you hold partner credentials and want to add the remaining surface:

1. Capture a known-good request/response pair (e.g. via proxy).
2. Add a new function in `robokassa/partner.py` following the pattern of
   `partner_refund`: typed dataclass for the response, `async def` for the
   call, pass `auth_headers` as a parameter.
3. Expose as an `@mcp.tool()` in `robokassa_mcp/server.py` so agents can
   drive it.
4. Add unit tests in `tests/test_partner_*.py` using `httpx.MockTransport`.

## Auth

Partner API auth is documented vaguely ("JWT-requests with parameters, signed
with a digital signature"). In practice, exact mechanics depend on the
partner agreement. The module exposes `auth_headers` as a dict — callers
build it per their setup (common patterns: `Authorization: Bearer <jwt>`,
signed timestamps, or IP-filtering with no auth header).
