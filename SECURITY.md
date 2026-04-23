# Security Policy

## Threat model

This server exposes tools that **move real money**: `create_invoice` produces
signed payment links, `refund_create` initiates refunds, `recurring_charge`
silently debits cards, `hold_confirm` captures pre-authorized funds. Any
integrator that connects an LLM to this MCP server accepts the risk that a
malicious prompt (direct or indirect injection) could cause financial loss.

This document lists the mitigations every integrator should apply and the
process for reporting vulnerabilities in the server itself.

## Integrator responsibilities

### 1. Human confirmation on state-changing tools

Require an explicit human approval step before any of these tools execute:

- `create_invoice` / `init_recurring_parent` / `hold_init` — may generate
  payment links that can be phished.
- `refund_create` / `partner_refund` — move funds back to the customer.
- `recurring_charge` — silently debits a stored card.
- `hold_confirm` / `hold_cancel` — finalizes or releases reserved funds.
- `second_receipt_create` — creates fiscal documents (auditable, hard to
  reverse).
- `send_sms` — costs money per send; abuse = financial damage.

Read-only tools (`check_payment`, `list_currencies`, `calc_out_sum`,
`refund_status`, `second_receipt_status`, `verify_*_signature`) can run
without approval in most contexts.

### 2. Validate parameters against a trusted source

Never trust amounts, recipient emails, or `inv_id` values that came from
LLM output alone. Cross-check against your own database before invoking
payment-moving tools. Example: if the agent says "refund inv_id 12345 for
`foo@example.com`", verify that invoice 12345 was created by that customer
in your records before calling `refund_create`.

### 3. Use test mode during development

Pass `is_test=True` to `create_invoice` while developing. Consider setting
`ROBOKASSA_LOGIN` to a separate test shop identifier in non-production
environments.

### 4. Rotate secrets on compromise

`Password#1`, `Password#2`, and `Password#3` can be regenerated in the
Robokassa cabinet. If any credentials leak (including via LLM logs), rotate
them immediately and audit the operations log for the period of exposure.

### 5. Scope Refund API access

`Password#3` is distinct from `Password#1/2` and must be explicitly enabled
for Refund API access in the cabinet. Only grant it to environments that
genuinely need to initiate refunds.

## Known limitations

- **No native rate limiting.** The server does not throttle tool invocations;
  wrap it in your own middleware if you need that.
- **Partner API auth varies.** `partner_refund` accepts arbitrary
  `auth_headers` — the caller is responsible for constructing a valid
  token; the server performs no additional validation.
- **Webhook signature verification is advisory.** `verify_result_signature`
  and `verify_success_signature` return a boolean; integrators must act on
  it (return 403 on false, etc.).

## Reporting a vulnerability

Please report security issues via
[GitHub Security Advisories](https://github.com/artgas1/robokassa-mcp/security/advisories/new).

Avoid filing a public issue for anything that affects operational security
(signature verification, credential handling, injection vectors). For
non-sensitive bugs, a regular issue is fine.

Maintenance posture is **drop-and-forget** — responses are best-effort, not
guaranteed. If an issue is urgent and unaddressed, feel free to fork and
patch.
