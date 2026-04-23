# Changelog

All notable changes to this project will be documented in this file.

## [0.1.1] - 2026-04-24

### Fixed

- `server.json` description trimmed to fit MCP Registry's 100-char limit.
  v0.1.0 was published to PyPI successfully, but registry rejected the
  initial manifest (422 Unprocessable Entity, length 170). v0.1.1 is the
  same library with the corrected manifest.

## [0.1.0] - 2026-04-24

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
- FastMCP server exposing 18 tools to AI agents
- Multi-arch Docker image at `ghcr.io/artgas1/robokassa-mcp`
