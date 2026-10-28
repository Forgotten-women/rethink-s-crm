"""
Which permission each API endpoint needs (RBAC, see core/rbac.py). Enforced on the server by the router guards
(api_access_guard / tracker_access_guard) for the charity the request is about - nothing the browser sends can
change it.

Deny by default: an endpoint missing from ROUTE_PERMISSIONS is refused (403) and scripts/test_isolation.py fails,
so a new endpoint can never be left open by accident.

Values:
  "donors.edit"                - that permission, for the charity the request is about
  AnyOf("a.view", "b.view")    - any one of them (endpoints shared by several pages)
  AllOf("email.campaigns", "email.send")
  SIGNED_IN                    - any signed-in account (charity isolation still applies)
  SUPER                        - super admins only
  PUBLIC                       - no session (own token / signature / key checks)
"""
from typing import Dict, Tuple, Union

SIGNED_IN = "@signed_in"
SUPER = "@super_admin"
PUBLIC = "@public"


class AnyOf(tuple):
    def __new__(cls, *perms):
        return super().__new__(cls, perms)


class AllOf(tuple):
    def __new__(cls, *perms):
        return super().__new__(cls, perms)


Requirement = Union[str, AnyOf, AllOf]

_CODE_LISTS = AnyOf("classifications.view", "explorer.view", "payouts.view", "stripe.view", "expenses.view",
                    "fundraisers.view", "tracker.view", "donors.view")

ROUTE_PERMISSIONS: Dict[str, Requirement] = {
    # --- auth / session ------------------------------------------------------------------------------------
    "auth.login_endpoint": PUBLIC,
    "auth.get_me_endpoint": SIGNED_IN,
    "auth.change_password_endpoint": SIGNED_IN,
    "cache_versions.data_versions": SIGNED_IN,
    "stream.stream_versions": SIGNED_IN,
    "main.health_check": PUBLIC,
    "filters.get_filter_options": SIGNED_IN,
    # --- dashboard -----------------------------------------------------------------------------------------
    "metrics.get_metrics_summary": "dashboard.view",
    "overview.get_overview_timeline": "dashboard.view",
    "overview.get_overview_headings": "dashboard.view",
    "overview.get_overview_top_campaigns": "dashboard.view",
    "overview.get_overview_subheadings": "dashboard.view",
    "ltv.get_ltv_summary": "dashboard.view",
    "donors.get_donors_kanban": "dashboard.view",
    # --- explorer / donors ---------------------------------------------------------------------------------
    "donors.get_donors_paginated": "explorer.view",
    "donors.update_single_donor_record": "explorer.edit",
    "donors.bulk_edit_donors": "explorer.bulk_edit",
    "donors.export_donors": AnyOf("explorer.export", "donors.export"),
    "donors.get_donation_detail": AnyOf("explorer.view", "donors.view"),
    "donors.get_campaigns_list": SIGNED_IN,
    "donors.get_donor_360_profile": "donors.view",
    "donors.get_segment_options": "donors.view",
    "donors.get_donor_directory": "donors.view",
    "donors.get_donor_history_paginated": "donors.view",
    "donors.list_agents": "donors.view",
    "donors.list_donor_notes": "donors.view",
    "donors.add_donor_note": "donors.edit",
    "donors.delete_donor_note": "donors.delete",
    "donors.update_donor": "donors.edit",
    "donors.set_donor_profile": "donors.edit",
    "donors.create_manual_donation": "donors.create",
    "donors.create_manual_donor": "donors.create",
    "donors.delete_manual_donation": "donors.delete",
    # --- classifications -----------------------------------------------------------------------------------
    "classifications.get_master_project_codes": _CODE_LISTS,
    "classifications.get_campaign_codes_lookup": _CODE_LISTS,
    "classifications.get_code_map": _CODE_LISTS,
    "classifications.get_launchgood_matrix": "classifications.view",
    "classifications.get_givebright_matrix": "classifications.view",
    "classifications.get_paysuite_matrix": "classifications.view",
    "classifications.get_rethink_website_matrix": "classifications.view",
    "classifications.get_madinah_matrix": "classifications.view",
    "classifications.get_stripe_matrix": "classifications.view",
    "classifications.export_classifications": "classifications.export",
    "classifications.save_matrix_rules": "classifications.edit",
    "classifications.sync_stripe_payment_links": "classifications.edit",
    "classifications.delete_single_rule": "classifications.delete",
    "classifications.clear_platform_rules": "classifications.delete",
    "classifications.import_classification_file": "classifications.import",
    "classifications.save_master_project_code": "classifications.master_codes",
    "classifications.update_master_code_status": "classifications.master_codes",
    "classifications.delete_master_project_code": "classifications.master_codes",
    # --- admin: data, charities, (legacy) users ------------------------------------------------------------
    "admin.get_system_status": "data.view",
    "admin.get_dataset_tags": "data.view",
    "admin.rename_dataset_tag": "data.tags",
    "admin.delete_dataset_tag": "data.tags",
    "admin.purge_database": "data.purge",
    "admin.purge_payouts_endpoint": "data.purge",
    "admin.upload_raw_data_file": "data.upload",
    "admin.list_companies_endpoint": SIGNED_IN,
    "admin.upsert_company_endpoint": "charities.edit",
    "admin.upload_company_logo_endpoint": "charities.edit",
    "admin.get_company_logo_endpoint": PUBLIC,
    "admin.get_users_list": SUPER,                 # legacy user screen, replaced by /api/rbac
    "admin.update_user_permission_endpoint": SUPER,
    "admin.assign_preset_endpoint": SUPER,
    "admin.edit_user_endpoint": SUPER,
    # --- expenses ------------------------------------------------------------------------------------------
    "expenses.get_project_codes": AnyOf("expenses.view", "classifications.view"),
    "expenses.get_expense_requests": "expenses.view",
    "expenses.get_code_transfers": "expenses.view",
    "expenses.export_expense_requests": "expenses.export",
    "expenses.export_transfers": "expenses.export",
    "expenses.submit_expense": "expenses.submit",
    "expenses.review_expense": "expenses.approve",
    "expenses.delete_expense": "expenses.delete",
    "expenses.create_code_transfer": "expenses.transfers",
    "expenses.void_code_transfer": "expenses.transfers",
    "expenses.get_expense_settings": SUPER,                      # global (every charity) SMTP settings
    "expenses.update_expense_settings": SUPER,                      # global (every charity) SMTP settings
    "expenses.test_smtp_email": SUPER,                      # global (every charity) SMTP settings
    "expenses.show_email_approval_page": PUBLIC,    # single-use approval token
    "expenses.handle_email_approval_post": PUBLIC,
    # --- payouts / stripe ----------------------------------------------------------------------------------
    "payouts.get_payouts_summary": "payouts.view",
    "payouts.get_payout_platforms": "payouts.view",
    "payouts.get_payout_batches": "payouts.view",
    "payouts.get_payout_ledger_breakdown": "payouts.view",
    "payouts.get_campaign_payout_breakdown": "payouts.view",
    "payouts.get_payout_donors": "payouts.view",
    "payouts.get_payout_ledger": "payouts.view",
    "payouts.get_paysuite_sync_status": "payouts.view",
    "payouts.get_paysuite_disbursals": "payouts.view",
    "payouts.update_payout_classification": "payouts.classify",
    "payouts.export_payouts_excel": "payouts.export",
    "payouts.trigger_paysuite_sync": "payouts.sync",
    "stripe_payouts.get_stripe_payouts": "stripe.view",
    "stripe_payouts.get_payout_items": "stripe.view",
    "stripe_payouts.needs_classification": "stripe.view",
    "stripe_payouts.ledger_summary": "stripe.view",
    "stripe_payouts.stripe_accounts": AnyOf("stripe.view", "payouts.view"),
    "stripe_payouts.run_payout_reconciliation": "stripe.reconcile",
    "stripe_payouts.resync_payout_classifications": "stripe.reconcile",
    "stripe_payouts.classify_line": "stripe.reconcile",
    "stripe_payouts.approve_payout": "stripe.approve",
    "stripe_payouts.resend_to_slack": "stripe.approve",
    "stripe_payouts.download_enriched_csv": "stripe.export",
    "stripe_payouts.export_stripe_payouts_excel": "stripe.export",
    # --- fundraisers ---------------------------------------------------------------------------------------
    "fundraisers.get_fundraisers_list": "fundraisers.view",
    "fundraisers.get_fundraiser_detail": "fundraisers.view",
    "fundraisers.get_fundraiser_statuses": "fundraisers.view",
    "fundraisers.resolve_fundraiser_link": "fundraisers.view",
    "fundraisers.get_ramadan_periods": "fundraisers.view",
    "fundraisers.get_available_campaigns_list": "fundraisers.view",
    "fundraisers.sync_discovered_fundraisers": "fundraisers.sync",
    "fundraisers.update_ramadan_periods": "fundraisers.edit",
    "fundraisers.create_fundraiser": "fundraisers.edit",
    "fundraisers.update_fundraiser": "fundraisers.edit",
    "fundraisers.assign_unassigned_donations": "fundraisers.edit",
    "fundraisers.add_fundraiser_link": "fundraisers.edit",
    "fundraisers.remove_fundraiser_link": "fundraisers.edit",
    "fundraisers.delete_fundraiser": "fundraisers.delete",
    # --- sponsorship tracker -------------------------------------------------------------------------------
    "tracker.get_targets": "tracker.view",
    "tracker.update_targets": "tracker.settings",
    "tracker.get_tracker_stats": "tracker.view",
    "tracker.get_tracker_page_data": "tracker.view",
    "tracker.get_beneficiaries": "tracker.view",
    "tracker.get_qualifying_donors": "tracker.view",
    "tracker.get_qualifying_campaigns": "tracker.view",
    "tracker.search_any_donor": "tracker.view",
    "tracker.list_manual_donors": "tracker.view",
    "tracker.get_classification_options": "tracker.view",
    "tracker.get_allocations": "tracker.view",
    "tracker.list_allocation_donors": "tracker.view",
    "tracker.get_feedbacks": "tracker.view",
    "tracker.get_allocation_communications": AnyOf("tracker.view", "email.view"),
    "tracker.get_email_tracking_status": AnyOf("tracker.view", "email.view"),
    "tracker.get_overdue_summary": "tracker.view",
    "tracker.get_overdue_donors": "tracker.view",
    "tracker.get_overdue_campaigns": "tracker.view",
    "tracker.get_overdue_dismissals": "tracker.view",
    "tracker.get_overdue_settings": "tracker.view",
    "tracker.get_sponsorship_donor_details": AnyOf("tracker.view", "donors.view"),
    "tracker.download_beneficiary_import_template": "tracker.import",
    "tracker.create_beneficiary": "tracker.edit",
    "tracker.update_beneficiary": "tracker.edit",
    "tracker.create_manual_donor": "tracker.edit",
    "tracker.update_manual_donor": "tracker.edit",
    "tracker.classify_donor": "tracker.edit",
    "tracker.classify_campaign": "tracker.edit",
    "tracker.create_allocation": "tracker.edit",
    "tracker.update_allocation": "tracker.edit",
    "tracker.renew_allocation": "tracker.edit",
    "tracker.update_allocation_dates": "tracker.edit",
    "tracker.add_allocation_donor": "tracker.edit",
    "tracker.update_allocation_donor": "tracker.edit",
    "tracker.create_feedback": "tracker.edit",
    "tracker.dismiss_overdue_alert": "tracker.edit",
    "tracker.undismiss_overdue_alert": "tracker.edit",
    "tracker.update_overdue_settings": "tracker.settings",
    "tracker.import_beneficiaries": "tracker.import",
    "tracker.delete_beneficiary": "tracker.delete",
    "tracker.delete_manual_donor": "tracker.delete",
    "tracker.delete_allocation": "tracker.delete",
    "tracker.remove_allocation_donor": "tracker.delete",
    "tracker.delete_feedback": "tracker.delete",
    # tracker: email + mailbox
    "tracker.get_email_templates": "email.view",
    "tracker.update_email_template": "email.templates",
    "tracker.delete_email_template": "email.templates",
    "tracker.reset_default_email_templates": "email.templates",
    "tracker.preview_email": "email.view",
    "tracker.get_bulk_email_recipients": "email.view",
    "tracker.preview_bulk_email": "email.view",
    "tracker.list_email_queue": "email.view",
    "tracker.trigger_queue_generation": "email.templates",
    "tracker.skip_email_queue_items": "email.templates",
    "tracker.send_bulk_email": "email.send",
    "tracker.send_outlook_message": "email.send",
    "tracker.send_email_queue_items": "email.send",
    "tracker.send_overdue_digest": "email.send",
    "tracker.get_outlook_status": "mailbox.view",
    "tracker.trigger_sync_replies": "mailbox.sync",
    "tracker.save_outlook_credentials": "mailbox.configure",
    "tracker.get_outlook_auth_url": "mailbox.configure",
    "tracker.exchange_outlook_token": "mailbox.configure",
    "tracker.disconnect_outlook": "mailbox.configure",
    "tracker.setup_outlook_subscription": "mailbox.configure",
    "tracker.renew_outlook_subscription": "mailbox.configure",
    "tracker.test_send_outlook_message": "mailbox.configure",
    "tracker.outlook_graph_webhook": PUBLIC,          # Microsoft Graph; checked by subscription id
    "tracker.email_tracking_pixel": PUBLIC,           # opened by the recipient's mail client
    # --- direct donor email --------------------------------------------------------------------------------
    "donor_email.recipients": "email.view",
    "donor_email.preview": "email.view",
    "donor_email.check_recipients": "email.view",
    "donor_email.recipient_gifts": "email.view",
    "donor_email.donor_email_history": "email.view",
    "donor_email.donor_email_thread": "email.view",
    "donor_email.email_activity": "email.view",
    "donor_email.list_campaigns": "email.view",
    "donor_email.campaign_messages": "email.view",
    "donor_email.send": "email.send",
    "donor_email.create_campaign": "email.campaigns",
    "donor_email.send_campaign_batch": AllOf("email.campaigns", "email.send"),
    "donor_email.cancel_campaign": "email.campaigns",
    "donor_email.delete_campaign": "email.campaigns",
    # --- unsubscribes / mailbox ----------------------------------------------------------------------------
    "unsubscribe.unsubscribe_page": PUBLIC,           # HMAC-signed link
    "unsubscribe.unsubscribe_confirm": PUBLIC,
    "unsubscribe.list_unsubscribes": "email.view",
    "unsubscribe.unseen_count": "email.view",
    "unsubscribe.mark_seen": "email.view",
    "unsubscribe.resubscribe": "email.resubscribe",
    "mailbox.mailbox_status": "mailbox.view",
    "mailbox.mailbox_sync_replies": "mailbox.sync",
    "mailbox.set_provider": "mailbox.configure",
    "mailbox.save_gmail_credentials": "mailbox.configure",
    "mailbox.gmail_auth_url": "mailbox.configure",
    "mailbox.gmail_exchange": "mailbox.configure",
    "mailbox.gmail_disconnect": "mailbox.configure",
    "mailbox.mailbox_test_send": "mailbox.configure",
    # --- access control (finer rules inside backend/api/rbac.py) -------------------------------------------
    "rbac.get_catalogue": SIGNED_IN,
    "rbac.list_roles": "users.view",
    "rbac.create_role": "users.presets",
    "rbac.update_role": "users.presets",
    "rbac.delete_role": "users.presets",
    "rbac.list_users": "users.view",
    "rbac.user_effective": "users.view",
    "rbac.create_user": "users.manage",
    "rbac.update_user": "users.manage",
    "rbac.set_user_access": "users.manage",
    "rbac.sign_out_everywhere": "users.manage",
    "rbac.scope_options": "users.manage",
    "rbac.set_super_admin": SUPER,
    "rbac.delete_user": SUPER,
    # --- platform webhooks / ops (own checks) --------------------------------------------------------------
    "webhooks.givebrite_webhook_rethink": PUBLIC,     # shared-secret header, off unless enabled
    "webhooks.givebrite_webhook_iqra": PUBLIC,
    "webhooks.givebrite_webhook_dynamic": PUBLIC,
    "webhooks.get_givebrite_webhook_logs": SUPER,
    "webhooks.trigger_givebrite_live_sync": SUPER,
    "webhooks.trigger_givebrite_backfill": SUPER,
    "ops.ops_status": SUPER,
    "ops.ops_logs": "logs.view",                    # filtered to the viewer's charities (backend/api/ops.py)
    "ops.list_sessions": SUPER,
    "ops.upload_session": SUPER,
    "ops.ops_cache_status": SUPER,
    "ops.ops_cache_clear": SUPER,
    "ops.sync_helper_key": SUPER,
    "ops.sync_helper_upload": PUBLIC,                 # server-held sync key (or a super admin session)
    "ops.sync_helper_csv": PUBLIC,
}


# File exports that contain donor contact details (they can't be masked like JSON): need donors.contact too.
CONTACT_EXPORTS = {"donors.export_donors", "payouts.export_payouts_excel", "stripe_payouts.download_enriched_csv",
                   "stripe_payouts.export_stripe_payouts_excel"}

# Endpoints that apply a person's fundraiser limit (core.rbac.scope_donations / request_scope). In a charity where
# someone is limited to specific fundraisers, every other endpoint is refused - pages such as the dashboard or
# payouts show charity-wide figures and would leak beyond their fundraisers.
SCOPE_AWARE = {
    "donors.get_donors_paginated", "donors.export_donors", "donors.get_donation_detail", "donors.get_donor_360_profile",
    "donors.get_segment_options", "donors.get_donor_directory", "donors.get_donor_history_paginated",
    "donors.list_donor_notes", "donors.list_agents",
    "fundraisers.get_fundraisers_list", "fundraisers.get_fundraiser_detail", "fundraisers.get_fundraiser_statuses",
    "fundraisers.get_ramadan_periods",
    "classifications.get_master_project_codes", "classifications.get_campaign_codes_lookup", "classifications.get_code_map",
}
# ... and these only for a fundraiser inside the person's list (fundraiser_id in the path)
SCOPED_FUNDRAISER_WRITES = {"fundraisers.update_fundraiser", "fundraisers.add_fundraiser_link",
                            "fundraisers.remove_fundraiser_link"}


def endpoint_key(endpoint) -> str:
    import inspect
    fn = inspect.unwrap(endpoint)
    return f"{fn.__module__.split('.')[-1]}.{fn.__name__}"


def requirement_for(endpoint) -> Requirement:
    return ROUTE_PERMISSIONS.get(endpoint_key(endpoint)) if endpoint is not None else None


def describe(req: Requirement) -> str:
    if isinstance(req, AnyOf):
        return " or ".join(req)
    if isinstance(req, AllOf):
        return " and ".join(req)
    return str(req)
