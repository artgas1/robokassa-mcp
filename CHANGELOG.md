# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added

- Complete checkout URL builder with 54-ФЗ fiscal receipts
- OpStateExt XML status endpoint with full state-code enum
- Refund API: Create + GetState (JWT HS256 with Password#3)
- Webhook signature helpers for ResultURL / SuccessURL (MD5 + SHA-*)
- Holding / pre-authorization: init, confirm, cancel
- Recurring payments: parent + child charges
- 54-ФЗ second receipt emission: /RoboFiscal/Receipt/Attach + Status
- Partner API RefundOperation (alternative refund path)
- Split (marketplace) payment URL builder
- SMS sending via Robokassa's SMS service
- XML Interfaces: GetCurrencies, CalcOutSumm
- `RobokassaClient` convenience wrapper with async context manager
- FastMCP server exposing 8 tools to AI agents

Not yet released — first release will be `0.1.0`.
