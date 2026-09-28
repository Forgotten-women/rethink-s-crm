# GiveBrite Iqra - Webhook Missing Data Gap Window

## Overview
This document records the exact missing data gap window for **GiveBrite (Iqra)** prior to the live webhook integration being connected on September 18, 2026.

---

## Gap Window Details

| Metric | Value |
|---|---|
| **Platform** | GiveBrite |
| **Tenant / Charity** | Iqra (`company_id: iqra`) |
| **Gap Start Timestamp (Last Historical Payment)** | **`2026-09-07 05:49:02 UTC`** |
| **Gap End Timestamp (First Live Webhook Event)** | **`2026-09-18 13:21:18 UTC`** |
| **Duration of Gap** | **11 Days, 7 Hours, 32 Minutes** |

---

## Boundary Records

### 1. Last Historical Payment Before Webhook Update
* **Donation ID**: `6a9e423eeaec1c81eec4fadf`
* **Date & Time (UTC)**: `2026-09-07 05:49:02`
* **Campaign**: `One With Gaza`
* **Donor**: `Mohammed Junaid Hossain`
* **Amount**: `£1.00`
* **Status**: In Database

### 2. First Live Webhook Event Received
* **Event ID**: `105`
* **Date & Time (UTC)**: `2026-09-18 13:21:18`
* **Event Type**: `donation.create`
* **Campaign**: `SISTERS' PROJECT: THE FORGOTTEN OF SHAAM`
* **Status**: Ingested via Webhook

---

## Action Required for Reconciliation
To backfill any transactions that occurred during this gap window:
1. Export the donations CSV from GiveBrite for the date range:
   **`2026-09-07` to `2026-09-18`**.
2. Filter/import records with timestamps between **`2026-09-07 05:49:03 UTC`** and **`2026-09-18 13:21:17 UTC`**.
