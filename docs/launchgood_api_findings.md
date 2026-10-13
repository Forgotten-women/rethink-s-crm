# LaunchGood Platform API Discovery & Technical Findings

## 1. Executive Summary

This document consolidates all findings from the reverse-engineering and API discovery session on **LaunchGood v4** (`www.launchgood.com`), conducted using authenticated credentials for `admin@rethinkcharity.org.uk`.

All access was strictly read-only; **no changes were made to the CRM, database, or production datasets**. Session tokens were captured and stored temporarily in `/tmp/launchgood_tokens.json`.

---

## 2. Infrastructure & Authentication Architecture

- **Web Frontend**: Next.js (App Router v4 Single-Page Application).
- **Edge Security**: Cloudflare WAF / Turnstile Bot Management (`cf_clearance` cookie validation and TLS fingerprint inspection).
- **Core API Gateway**: `https://www.launchgood.com/api/`
- **Search & Analytics Gateway**: `https://search.launchgood.com/`
- **Auth Token Specifications**:
  - Format: RSA-signed JWT (`RS256`) Bearer token.
  - Issuer: `https://auth.launchgood.com`
  - Audience: `api.launchgood.com`
  - Lifespan: **15 minutes** (`900` seconds from `iat` to `exp`).
  - Refresh Mechanism: The frontend refreshes this token automatically using the persistent HTTP session cookie (`__cf_bm`, `cf_clearance`, and session identifiers).

---

## 3. Discovered Accounts & Organization Identity

Calling the user discovery endpoint (`POST https://www.launchgood.com/api/user/currentUser`) revealed the following profile for Rethink Charity:

- **User ID**: `1816824`
- **User Name**: `Rethink Charity`
- **Email**: `admin@rethinkcharity.org.uk`
- **Default Currency**: `GBP`
- **Default Subaccount ID**: `77506`
- **Linked Accounts**:
  | Account ID | Type | Name | Country | Purpose |
  |---|---|---|---|---|
  | **`31152`** | `corporate` | Rethink Charity's Business Account | `GB` | **Primary Fundraising & Bank Payout Account** (£3.73M lifetime volume) |
  | **`38926`** | `corporate` | Rethink Charity's Business Account | `GB` | Secondary corporate account |
  | **`46201`** | `personal` | Rethink Charity's Personal Account | `GB` | Personal user account |

---

## 4. Discovered API Endpoints & Capabilities

### 4.1. Financial Payouts & Bank Transfers API ⭐ *(Key Finding)*

LaunchGood features a dedicated internal endpoint that delivers complete historical bank transfers, fee breakdowns, and campaign disbursement distributions.

* **Endpoint**: `POST https://www.launchgood.com/api/account/transfers`
* **Method**: `POST`
* **Headers**:
  ```http
  Authorization: Bearer <TOKEN>
  Content-Type: application/json
  Cookie: <session_cookies>
  ```
* **Request Payload**:
  ```json
  {
    "account_id": 31152
  }
  ```
* **Data Discovered for Rethink Charity (Account 31152)**:
  * **Lifetime Total Disbursed**: **£3,738,456.05 GBP**
  * **Total Bank Payout Batches**: **32 completed transfers**

#### Payout Batch Response Schema:
Each transfer object in `result.transfers[0].transfers[]` contains exhaustive financial reconciliation fields:

| Field Name | Type | Description |
|---|---|---|
| `id` | integer | LaunchGood Transfer ID (e.g., `15702`, `16598`, `17516`) |
| `status` | string | Transfer status (e.g., `"Complete (Confirmed)"`) |
| `currency` | string | Settlement currency (`"GBP"`) |
| `sent` | ISO 8601 string | Timestamp when payout was initiated to the bank |
| `from` / `to` | ISO 8601 string | Date range of donations included in the payout batch |
| `gross_amount` | decimal string | Gross donation volume collected during the period |
| `gross_count` | integer | Number of individual donations collected |
| `processing_fees_amount` | decimal string | Payment processor transaction fees deducted |
| `non_processing_fees_amount` | decimal string | Platform fees deducted |
| `chargeback_amount` | decimal string | Total chargebacks deducted |
| `chargeback_fee_amount` | decimal string | Chargeback dispute fees |
| `refund_amount` | decimal string | Total refunded donations deducted |
| `net_sales_amount` | decimal string | Net sales before payout adjustments |
| `total_disbursement_amount` | decimal string | **Net amount deposited into Rethink's bank account** |
| `campaigns[]` | array | **Detailed breakdown of campaigns funded by this batch** |

#### Campaign Breakdown Inside Each Transfer:
Each payout batch explicitly itemizes which campaigns contributed to the payout:
```json
[
  {
    "project_id": 211948,
    "name": "Syria needs you Campaign",
    "amount": 196231.17
  },
  {
    "project_id": 197129,
    "name": "Mumtaz's Syrian & Gazan Challenge",
    "amount": 69896.93
  },
  {
    "project_id": 195323,
    "name": "Feed Syrian & Gazan Families",
    "amount": 51512.84
  }
]
```

---

### 4.2. User Profile & Discovery API

* **Endpoint**: `POST https://www.launchgood.com/api/user/currentUser`
* **Method**: `POST`
* **Payload**: `{}`
* **Returns**: Current authenticated user context, user ID, corporate subaccounts, enabled payment provider modes (`adyen`, `adyen-googlepay`, `adyen-applepay`), and feature flags.

---

### 4.3. Asynchronous Donation & Donor Export Reporting Engine

LaunchGood handles large volume donor and donation exports asynchronously through a three-stage pipeline:

#### Step 1: Initiate Report Job
* **Endpoint**: `POST https://www.launchgood.com/api/reports/v4_reports`
* **Payload**:
  ```json
  {
    "account_id": "31152",
    "type": "account_donors",
    "start": "2024-01-01T00:00:00.000Z",
    "end": "2024-03-31T23:59:59.999Z",
    "fmt": "csv",
    "settled_donations": true
  }
  ```
* **Response**:
  ```json
  {
    "success": true,
    "result": {
      "format": "csv",
      "identifier": "account_donor|AccountReport##31152##2024-01-01T00:00:00+00:00##2024-03-31T23:59:59+00:00##...",
      "label": "Account Donation Report"
    }
  }
  ```

#### Step 2: Trigger Generation Task
* **Endpoint**: `POST https://www.launchgood.com/api/reports/action`
* **Payload**:
  ```json
  {
    "verb": "generate",
    "format": "csv",
    "identifier": "<identifier_from_step_1>"
  }
  ```
* **Response**:
  ```json
  {
    "success": true,
    "result": {
      "state": "generating",
      "identifier": "67a2e7c6f663c54e4e07d534659caea6"
    }
  }
  ```

#### Step 3: Stream Progress & Final Download
* **Status Stream**: `GET https://www.launchgood.com/api/logStream/stream/<identifier>`
  * Listens to Server-Sent Events (SSE) until compilation reaches `100%`.
* **Download Action**: `POST https://www.launchgood.com/api/reports/action` with `verb: "download"`.

---

### 4.4. Supported Currencies & Platform Utilities

* **Endpoint**: `POST https://www.launchgood.com/api/fulladmin/currencies`
* **Payload**: `{}`
* **Response**:
  ```json
  {
    "success": true,
    "result": ["USD", "AUD", "CAD", "SGD", "NZD", "GBP", "EUR", "MYR"]
  }
  ```

---

### 4.5. Campaign OpenSearch API

* **Endpoint**: `GET https://search.launchgood.com/v2/production`
* **Purpose**: Fast search and indexing for campaigns, project reward tiers, and donor leaderboard aggregates by account ID.

---

## 5. Comparison: LaunchGood vs. GiveBrite Capabilities

| Capability | GiveBrite Public API | LaunchGood API |
|---|---|---|
| **Direct Payout Batch Endpoint** | ❌ None | ✅ `POST /api/account/transfers` |
| **Gross vs. Net Bank Reconciliation** | ❌ Not available | ✅ Exact `total_disbursement_amount` & fees |
| **Batch-to-Campaign Attribution** | ❌ Not available | ✅ `campaigns[]` list per transfer batch |
| **Merchant Processor API Access** | ❌ Stripe Express (Display-only) | ✅ Platform handles disbursements directly |
| **Live Donation Stream** | ✅ `GET /v1/dashboard/donations` | ⚠️ Handled via Asynchronous CSV Export |
| **Authentication Lifespan** | Long-lived JWT (~1 hour) | 15-minute JWT (auto-refreshed via cookies) |

---

## 6. Temporary Files Created

- `/tmp/launchgood_tokens.json`: Authenticated session headers, Bearer JWT, and cookies.
- `/tmp/launchgood_sample_transfers.json`: Full JSON sample of the 32 historical transfers (£3.73M) for Account `31152`.
- `docs/launchgood_api_findings.md`: This reference documentation.
