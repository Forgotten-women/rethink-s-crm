# GiveBrite Public API Integration: Technical Overview, Current Limitations & Data Requirements

**Document Purpose**: Official integration requirements and technical gap analysis for discussion with the GiveBrite technical & product teams.  
**Organization**: Rethink Charity / Iqra Charity  
**Target Platform**: GiveBrite Fundraising Platform (`givebrite.com`)  

---

## 1. Executive Summary

As a registered charity processing online fundraising through GiveBrite, our objective is to establish an automated, reliable data integration between GiveBrite and our central Charity CRM / Financial Ledger.

Currently, we are attempting to build our integration using **GiveBrite's public-facing developer capabilities** (endpoints accessible without private interactive dashboard sessions or session-based browser tokens). However, we face significant technical roadblocks—most notably the **lack of programmatic access to donation records, donor details, and financial payout/settlement batches**.

Because our underlying payment processor is configured under **Stripe Express**, we do not possess direct developer API access to Stripe. Consequently, **GiveBrite is our sole source of financial truth**, and we require official API capabilities to access our donation and settlement data programmatically.

---

## 2. Currently Accessible Public Endpoints (No Authentication Required)

The following endpoints represent the public surface currently accessible via standard HTTP requests without session tokens:

### 2.1. Public Charity Profile & Configuration
* **Endpoint**: `GET https://api.givebrite.com/v1/charity/{charity_id}?type=_id`
* **Accessibility**: Publicly open (HTTP 200 without headers)
* **Data Returned**:
  * Charity organization metadata (`name`, `slug`, `verified`, `regno`).
  * Branding assets (logo CDN links, color variants).
  * Feature flags (`is_zakat`, `gift_aid_enabled`, `recurring_enabled`).
  * Connected payment gateway type (`Stripe`).
* **Integration Limitation**: Provides high-level organizational configuration only; contains no transactional or donation records.

---

### 2.2. Public Campaign Listing & Summary
* **Endpoint**: `GET https://api.givebrite.com/v1/campaign/public?charity_id={charity_id}`
* **Accessibility**: Publicly open
* **Data Returned**:
  * Active public campaign cards (`_id`, `name`, `slug`, `target`, `total_raised`).
  * Basic display imagery and fundraiser counts.
* **Integration Limitation**: Returns aggregate display summaries only. Does not provide itemized donor lists, historical giving packages, or transaction ledgers.

---

### 2.3. Public Subdomain & Routing
* **Endpoint**: `GET https://api.givebrite.com/v1/dashboard/subdomain?type=live`
* **Accessibility**: Publicly open
* **Data Returned**:
  * Live domain mapping (`https://donate.iqracharity.org`) and DNS CNAME targets.

---

## 3. Critical Technical Limitations & Current Integration Roadblocks

When attempting to integrate external systems using GiveBrite’s public-facing APIs, we encounter five major technical limitations:

### 1. No Machine-to-Machine (M2M) API or Standard Developer API Key
* **The Roadblock**: GiveBrite currently lacks a dedicated public developer API with standard programmatic authentication (e.g., `X-API-KEY`, Static Bearer API Tokens, or OAuth2 Client Credentials).
* **Impact**: Endpoints containing donation details reside under dashboard controllers that reject external API requests with `HTTP 403 Forbidden` unless accessed through an interactive user session. Charities cannot integrate external CRM or accounting systems through standard machine-to-machine developer practices.

---

### 2. Complete Absence of Financial Payout & Bank Settlement Data
* **The Roadblock**: There is no public or partner API endpoint that exposes bank payout batches, settlement dates, or net disbursement amounts.
* **Impact**:
  * When GiveBrite deposits a lump-sum payout into the charity’s bank account, our finance team cannot programmatically determine:
    1. Which specific payout batch ID this deposit corresponds to.
    2. Which individual donations or campaigns constitute the lump-sum deposit.
    3. The exact breakdown of payment processing fees (Stripe fees) vs. platform fees deducted from the gross total.

---

### 3. Stripe Express Account Restriction (No Direct Stripe API Access)
* **The Roadblock**: Our Stripe integration with GiveBrite is provisioned as a **Stripe Express** account rather than Stripe Standard.
* **Impact**:
  * Stripe Express provides only an embedded, visual dashboard within the Stripe portal.
  * Stripe **does not grant secret API keys** (`sk_live_...` or `rk_live_...`) to Express account holders.
  * Therefore, we **cannot query Stripe directly** (e.g. `/v1/payouts` or `/v1/balance_transactions`) to perform reconciliation.
  * **GiveBrite is the only entity that holds this payout data**, making a GiveBrite settlement endpoint essential.

---

### 4. No Webhook Infrastructure for Real-Time Event Streaming
* **The Roadblock**: GiveBrite does not currently provide a webhook subscription system (e.g. `donation.created`, `donation.refunded`, `payout.paid`).
* **Impact**: Our systems cannot receive real-time notifications when a donor makes a contribution. Instead, staff are forced to manually log in to the dashboard to export CSV spreadsheets, introducing operational delays and human error.

---

### 5. Missing Campaign and Giving Level Mappings
* **The Roadblock**: In publicly queryable campaign structures, individual giving levels and custom impact packages (e.g., "£30 - Emergency Food Parcel", "£100 - Medical Aid") are not exposed in a consistent relational format.
* **Impact**: When donations are received, downstream CRM systems cannot automatically categorize funds into restricted charity project codes without manual intervention.

---

## 4. What Data We Need (Required Data Schema)

To establish an automated, audit-compliant integration, we require programmatic access to two primary datasets:

### 4.1. Dataset A: Automated Inward Donations Feed
We require an endpoint (or webhook) that provides the following fields for every donation:

| Field Name | Description | Purpose |
|---|---|---|
| `donation_id` | Unique GiveBrite transaction identifier | Deduplication & tracking |
| `transaction_date` | Timestamp (ISO 8601) of transaction | CRM timeline |
| `donor_first_name` | Donor's first name | Donor care & receipts |
| `donor_last_name` | Donor's last name | Donor care & receipts |
| `donor_email` | Donor's email address | Automated receipting |
| `gross_amount` | Total amount charged to donor | Revenue accounting |
| `currency` | Currency code (`GBP`, `USD`, `EUR`) | Multi-currency accounting |
| `is_gift_aid` | Boolean Gift Aid declaration flag | HMRC Gift Aid submission |
| `donor_address` | Full address and postal code | Statutory Gift Aid validation |
| `campaign_id` | Unique ID of the campaign | Fund allocation |
| `campaign_name` | Full title of the campaign | Reporting |
| `giving_level` | Selected giving level or impact package | Restricted project tracking |
| `payment_method` | Payment channel (`card`, `applePay`, `googlePay`) | Merchant reconciliation |
| `gateway_fee` | Processing fee deducted at donation | Transaction-level expense |

---

### 4.2. Dataset B: Payout Batches & Bank Settlement Records
We require an endpoint that provides settlement data for each bank deposit:

| Field Name | Description | Purpose |
|---|---|---|
| `payout_batch_id` | Unique GiveBrite Transfer / Payout identifier | Bank statement matching |
| `payout_date` | Date the funds were released to the bank | Cash receipt tracking |
| `period_start` / `period_end` | Date range of donations included in batch | Accounting period cut-off |
| `gross_amount` | Total gross donations in this payout batch | Income verification |
| `processing_fees` | Total Stripe payment processing fees deducted | Expense ledger entry |
| `platform_fees` | Total GiveBrite platform fees deducted | Platform expense entry |
| `refunds_deducted` | Total refunds or chargebacks withheld | Adjustments ledger |
| `net_disbursed_amount` | **Exact net amount deposited into bank** | **1-to-1 bank reconciliation** |
| `payout_status` | Status (e.g., `Paid`, `Pending`, `Confirmed`) | Cash flow monitoring |
| `included_campaigns` | Array of campaigns and amounts in this batch | Project fund distribution |
| `included_donation_ids` | Array of donation IDs contributing to this payout | Transaction-level audit trail |

---

## 5. Why We Want This Data (Business & Regulatory Rationale)

1. **Automated Bank Reconciliation (Critical Priority)**:
   * Our bank statements show lump-sum deposits (e.g. `£8,452.19 GBPOUT`).
   * Without a payout API, our finance team cannot match this figure to our records without manually downloading CSV reports, creating a multi-day reconciliation backlog.

2. **Compliance with Charity Accounting Standards (SORP)**:
   * UK Charity Commission regulations require registered charities to record charitable income **gross** and report payment processing / platform fees as distinct **expenditures**.
   * Lacking fee breakdowns forces manual estimates, complicating year-end statutory financial audits.

3. **Restricted Fund & Zakat Accountability**:
   * Charitable donations are legally restricted to designated humanitarian causes (e.g., Gaza Emergency, Orphan Sponsorship, Zakat).
   * We must track exactly when cash for each specific fund arrives in our bank account so it can be deployed immediately to field operations.

4. **HMRC Gift Aid Claims**:
   * Gift Aid represents an additional 25% in funding on eligible UK donations.
   * Direct automated access to donor names, full addresses, and Gift Aid declarations is essential for generating compliant HMRC audit schedules.

---

## 6. Proposed Solutions / Path Forward with GiveBrite

We invite the GiveBrite technical team to consider one of the following solutions:

1. **Solution 1 (Preferred): Standard API Key / Partner Developer Access**:
   * Provision a static API key for our charity organization to query read-only endpoints for `/v1/donations` and `/v1/payouts` over HTTPS.
2. **Solution 2: Automated Webhooks**:
   * Implement webhook endpoints to push `donation.succeeded` and `payout.disbursed` events directly to our secure HTTPS endpoint.
3. **Solution 3: Scheduled Payout & Donation SFTP / S3 Export**:
   * If real-time APIs are not currently on the public roadmap, enable automated daily/weekly exports of donation and payout reconciliation reports to a secure cloud destination.
