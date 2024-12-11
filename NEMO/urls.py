import logging
import os
from importlib import import_module

from django.apps import apps
from django.conf import settings
from django.conf.urls import include
from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LogoutView
from django.contrib.staticfiles.storage import staticfiles_storage
from django.urls import path, re_path
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.generic import RedirectView
from django.views.static import serve
from rest_framework import routers

from NEMO.constants import MEDIA_PROTECTED
from NEMO.decorators import any_staff_required
from NEMO.models import ReservationItemType
from NEMO.views import (
    abuse,
    access_requests,
    accounts_and_projects,
    adjustment_requests,
    alerts,
    api,
    api_file_import,
    area_access,
    authentication,
    buddy_requests,
    calendar,
    charge_validation,
    configuration_agenda,
    consumables,
    contact_staff,
    customization,
    documents,
    email,
    event_details,
    feedback,
    get_projects,
    history,
    jumbotron,
    knowledge_base,
    landing,
    maintenance,
    mobile,
    news,
    qualifications,
    remote_work,
    resources,
    safety,
    sidebar,
    status_dashboard,
    tasks,
    timed_services,
    tool_control,
    tool_credentials,
    training,
    tutorials,
    usage,
    user_requests,
    users,
)

logger = logging.getLogger(__name__)


def sort_urls(url_path):
    return url_path[0].count("/"), url_path[0]


# REST API URLs
router = routers.DefaultRouter()
router.register(r"account_types", api.AccountTypeViewSet)
router.register(r"accounts", api.AccountViewSet)
router.register(r"adjustment_requests", api.AdjustmentRequestViewSet)
router.register(r"alert_categories", api.AlertCategoryViewSet)
router.register(r"alerts", api.AlertViewSet)
router.register(r"area_access_records", api.AreaAccessRecordViewSet)
router.register(r"areas", api.AreaViewSet)
router.register(r"auth_groups", api.GroupViewSet)
router.register(r"auth_permissions", api.PermissionViewSet)
router.register(r"billing", api.BillingViewSet, basename="billing")
router.register(r"buddy_requests", api.BuddyRequestViewSet)
router.register(r"configurations", api.ConfigurationViewSet)
router.register(r"consumable_categories", api.ConsumableCategoryViewSet)
router.register(r"consumable_withdrawals", api.ConsumableWithdrawViewSet)
router.register(r"consumables", api.ConsumableViewSet)
router.register(r"content_types", api.ContentTypeViewSet)
router.register(r"interlock_card_categories", api.InterlockCardCategoryViewSet)
router.register(r"interlock_cards", api.InterlockCardViewSet)
router.register(r"interlocks", api.InterlockViewSet)
router.register(r"physical_access_levels", api.PhysicalAccessLevelViewSet)
router.register(r"temporary_physical_access_requests", api.TemporaryPhysicalAccessRequestViewSet)
router.register(r"project_disciplines", api.ProjectDisciplineViewSet)
router.register(r"projects", api.ProjectViewSet)
router.register(r"qualifications", api.QualificationViewSet)
router.register(r"recurring_consumable_charges", api.RecurringConsumableChargesViewSet)
router.register(r"reservations", api.ReservationViewSet)
router.register(r"reservation_configuration_options", api.ConfigurationOptionViewSet)
router.register(r"resources", api.ResourceViewSet)
router.register(r"scheduled_outages", api.ScheduledOutageViewSet)
router.register(r"staff_charges", api.StaffChargeViewSet)
router.register(r"tasks", api.TaskViewSet)
router.register(r"tools", api.ToolViewSet)
router.register(r"tool_credentials", api.ToolCredentialsViewSet)
router.register(r"tool_status", api.ToolStatusViewSet, basename="tool_status")
router.register(r"training_sessions", api.TrainingSessionViewSet)
router.register(r"usage_events", api.UsageEventViewSet)
router.register(r"users", api.UserViewSet)
router.register(r"user_documents", api.UserDocumentsViewSet)
router.registry.sort(key=sort_urls)

reservation_item_types = f'(?P<item_type>{"|".join(ReservationItemType.values())})'

urlpatterns = []

# Include urls for all NEMO plugins (that start with prefix NEMO)
# URLs in plugins with exact same path will take precedence over regular NEMO URLs
# Note that the path MUST be the same, down to the last "/"
for app in apps.get_app_configs():
    app_name = app.name
    if app_name != "NEMO" and app_name.startswith("NEMO"):
        try:
            plugin_urls = "%s.urls" % app_name
            try:
                mod = import_module(plugin_urls)
            except ModuleNotFoundError as e:
                if e.name == plugin_urls:
                    logger.debug(f"no urls found for NEMO plugin: {app_name}")
                else:
                    raise
            else:
                urlpatterns += [path("", include(plugin_urls))]
                logger.debug(f"automatically including urls for plugin: {app_name}")
        except Exception:
            if getattr(app, "critical", False):
                raise
            else:
                logger.exception(f"Failure when loading URLs for app: {app_name}")

# The order matters for some tests to run properly
urlpatterns += [
    # Authentication & error pages:
    path("login/", authentication.login_user, name="login"),
    path(
        "logout/", LogoutView.as_view(next_page="landing" if not settings.LOGOUT_REDIRECT_URL else None), name="logout"
    ),
    path("impersonate/", authentication.impersonate, name="impersonate"),
    path("authorization_failed/", authentication.authorization_failed, name="authorization_failed"),
    # Root URL defaults to the calendar page on desktop systems, and the mobile homepage for mobile devices:
    path("", landing.landing, name="landing"),
    # Get a list of projects for a user:
    path(
        "get_projects_for_consumables/", get_projects.get_projects_for_consumables, name="get_projects_for_consumables"
    ),
    path("get_projects_for_training/", get_projects.get_projects_for_training, name="get_projects_for_training"),
    path(
        "get_projects_for_tool_control/",
        get_projects.get_projects_for_tool_control,
        name="get_projects_for_tool_control",
    ),
    path("get_projects_for_self/", get_projects.get_projects_for_self, name="get_projects_for_self"),
    # User Profile:
    path("user/view_user/<int:user_id>/", users.view_user, name="view_user"),
    # Tool control:
    # This tool_control URL is needed to be able to reverse when choosing items on mobile using next_page.
    # (see choose_item.html for details)
    re_path(r"^tool_control/(?P<item_type>(tool))/(?P<tool_id>\d+)/$", tool_control.tool_control, name="tool_control"),
    path("tool_control/<int:tool_id>/", tool_control.tool_control, name="tool_control"),
    path("tool_control/", tool_control.tool_control, name="tool_control"),
    path("tool_status/<int:tool_id>/", tool_control.tool_status, name="tool_status"),
    path("use_tool_for_other/", tool_control.use_tool_for_other, name="use_tool_for_other"),
    path("tool_configuration/", tool_control.tool_configuration, name="tool_configuration"),
    path("create_comment/", tool_control.create_comment, name="create_comment"),
    path("hide_comment/<str:comment_id>/", tool_control.hide_comment, name="hide_comment"),
    re_path(
        r"^enable_tool/(?P<tool_id>\d+)/user/(?P<user_id>\d+)/project/(?P<project_id>\d+)/staff_charge/(?P<staff_charge>(true|false))/$",
        tool_control.enable_tool,
        name="enable_tool",
    ),
    path("disable_tool/<int:tool_id>/", tool_control.disable_tool, name="disable_tool"),
    path("enter_wait_list/", tool_control.enter_wait_list, name="enter_wait_list"),
    path("exit_wait_list/", tool_control.exit_wait_list, name="exit_wait_list"),
    path("tool_config_history/<int:tool_id>/", tool_control.tool_config_history, name="tool_config_history"),
    path("usage_data_history/<int:tool_id>/", tool_control.usage_data_history, name="usage_data_history"),
    path("past_comments_and_tasks/", tool_control.past_comments_and_tasks, name="past_comments_and_tasks"),
    path(
        "ten_most_recent_past_comments_and_tasks/<int:tool_id>/",
        tool_control.ten_most_recent_past_comments_and_tasks,
        name="ten_most_recent_past_comments_and_tasks",
    ),
    path(
        "tool_usage_group_question/<int:tool_id>/<str:group_name>/",
        tool_control.tool_usage_group_question,
        name="tool_usage_group_question",
    ),
    path("reset_tool_counter/<int:counter_id>/", tool_control.reset_tool_counter, name="reset_tool_counter"),
    # User requests
    path("user_requests/", user_requests.user_requests, name="user_requests"),
    re_path(r"^user_requests/(?P<tab>buddy|access|adjustment)/$", user_requests.user_requests, name="user_requests"),
    # Access requests
    path("access_requests/", access_requests.access_requests, name="access_requests"),
    path("create_access_request/", access_requests.create_access_request, name="create_access_request"),
    path("edit_access_request/<int:request_id>/", access_requests.create_access_request, name="edit_access_request"),
    path("export_access_requests/", access_requests.csv_export, name="export_access_requests"),
    path(
        "delete_access_request/<int:request_id>/", access_requests.delete_access_request, name="delete_access_request"
    ),
    # Buddy System
    path("buddy_requests/", buddy_requests.buddy_requests, name="buddy_requests"),
    path("create_buddy_request/", buddy_requests.create_buddy_request, name="create_buddy_request"),
    path("edit_buddy_request/<int:request_id>/", buddy_requests.create_buddy_request, name="edit_buddy_request"),
    path("delete_buddy_request/<int:request_id>/", buddy_requests.delete_buddy_request, name="delete_buddy_request"),
    path("buddy_request_reply/<int:request_id>/", buddy_requests.buddy_request_reply, name="buddy_request_reply"),
    # Adjustment requests
    path("adjustment_requests/", adjustment_requests.adjustment_requests, name="adjustment_requests"),
    path("create_adjustment_request/", adjustment_requests.create_adjustment_request, name="create_adjustment_request"),
    path(
        "create_adjustment_request/<int:item_type_id>/<int:item_id>/",
        adjustment_requests.create_adjustment_request,
        name="create_adjustment_request",
    ),
    path(
        "edit_adjustment_request/<int:request_id>/",
        adjustment_requests.create_adjustment_request,
        name="edit_adjustment_request",
    ),
    path(
        "edit_adjustment_request/<int:request_id>/<int:item_type_id>/<int:item_id>/",
        adjustment_requests.create_adjustment_request,
        name="edit_adjustment_request",
    ),
    path(
        "adjustment_request_reply/<int:request_id>/",
        adjustment_requests.adjustment_request_reply,
        name="adjustment_request_reply",
    ),
    path("export_adjustment_requests/", adjustment_requests.csv_export, name="export_adjustment_requests"),
    path(
        "delete_adjustment_request/<int:request_id>/",
        adjustment_requests.delete_adjustment_request,
        name="delete_adjustment_request",
    ),
    path(
        "mark_adjustment_as_applied/<int:request_id>/",
        adjustment_requests.mark_adjustment_as_applied,
        name="mark_adjustment_as_applied",
    ),
    path(
        "apply_adjustment/<int:request_id>/",
        adjustment_requests.apply_adjustment,
        name="apply_adjustment",
    ),
    # Tasks:
    path("create_task/", tasks.create, name="create_task"),
    path("cancel_task/<int:task_id>/", tasks.cancel, name="cancel_task"),
    path("update_task/<int:task_id>/", tasks.update, name="update_task"),
    path("task_update_form/<int:task_id>/", tasks.task_update_form, name="task_update_form"),
    path("task_resolution_form/<int:task_id>/", tasks.task_resolution_form, name="task_resolution_form"),
    # Calendar:
    re_path(r"^calendar/" + reservation_item_types + "/(?P<item_id>\d+)/$", calendar.calendar, name="calendar"),
    path("calendar/", calendar.calendar, name="calendar"),
    path("event_feed/", calendar.event_feed, name="event_feed"),
    path("create_reservation/", calendar.create_reservation, name="create_reservation"),
    path("create_outage/", calendar.create_outage, name="create_outage"),
    path("resize_reservation/", calendar.resize_reservation, name="resize_reservation"),
    path("resize_outage/", calendar.resize_outage, name="resize_outage"),
    path("move_reservation/", calendar.move_reservation, name="move_reservation"),
    path("move_outage/", calendar.move_outage, name="move_outage"),
    path("cancel_reservation/<int:reservation_id>/", calendar.cancel_reservation, name="cancel_reservation"),
    path("cancel_outage/<int:outage_id>/", calendar.cancel_outage, name="cancel_outage"),
    path("set_reservation_title/<int:reservation_id>/", calendar.set_reservation_title, name="set_reservation_title"),
    path("change_outage_title/<int:outage_id>/", calendar.change_outage_title, name="change_outage_title"),
    path("change_outage_details/<int:outage_id>/", calendar.change_outage_details, name="change_outage_details"),
    path("change_reservation_date/", calendar.change_reservation_date, name="change_reservation_date"),
    path("change_outage_date/", calendar.change_outage_date, name="change_outage_date"),
    path(
        "change_reservation_project/<int:reservation_id>/",
        calendar.change_reservation_project,
        name="change_reservation_project",
    ),
    path("proxy_reservation/", calendar.proxy_reservation, name="proxy_reservation"),
    path(
        "reservation_group_question/<int:reservation_question_id>/<str:group_name>/",
        calendar.reservation_group_question,
        name="reservation_group_question",
    ),
    # Event Details:
    path(
        "event_details/reservation/<int:reservation_id>/", event_details.reservation_details, name="reservation_details"
    ),
    path("event_details/outage/<int:outage_id>/", event_details.outage_details, name="outage_details"),
    path("event_details/usage/<int:event_id>/", event_details.usage_details, name="usage_details"),
    path("event_details/area_access/<int:event_id>/", event_details.area_access_details, name="area_access_details"),
    # Qualifications:
    path("qualifications/", qualifications.qualifications, name="qualifications"),
    path("modify_qualifications/", qualifications.modify_qualifications, name="modify_qualifications"),
    path("get_qualified_users/", qualifications.get_qualified_users, name="get_qualified_users"),
    # Remote work:
    path("remote_work/", remote_work.remote_work, name="remote_work"),
    path("staff_charges/", remote_work.staff_charges, name="staff_charges"),
    path("begin_staff_charge/", remote_work.begin_staff_charge, name="begin_staff_charge"),
    path("begin_staff_area_charge/", remote_work.begin_staff_area_charge, name="begin_staff_area_charge"),
    path("end_staff_area_charge/", remote_work.end_staff_area_charge, name="end_staff_area_charge"),
    path("end_staff_charge/", remote_work.end_staff_charge, name="end_staff_charge"),
    path("edit_staff_charge_note/", remote_work.edit_staff_charge_note, name="edit_staff_charge_note"),
    path(
        "validate_staff_charge/<int:staff_charge_id>/",
        charge_validation.validate_staff_charge,
        name="validate_staff_charge",
    ),
    path(
        "validate_usage_event/<int:usage_event_id>/",
        charge_validation.validate_usage_event,
        name="validate_usage_event",
    ),
    path(
        "validate_area_access_record/<int:area_access_record_id>/",
        charge_validation.validate_area_access_record,
        name="validate_area_access_record",
    ),
    path(
        "validate_missed_reservation/<int:reservation_id>/",
        charge_validation.validate_missed_reservation,
        name="validate_missed_reservation",
    ),
    path(
        "validate_training_session/<int:training_session_id>/",
        charge_validation.validate_training_session,
        name="validate_training_session",
    ),
    path(
        "validate_consumable_withdraw/<int:consumable_withdraw_id>/",
        charge_validation.validate_consumable_withdrawal,
        name="validate_consumable_withdrawal",
    ),
    # Status dashboard:
    path("status_dashboard/", status_dashboard.status_dashboard, name="status_dashboard"),
    re_path(
        r"^status_dashboard/(?P<tab>tools|occupancy|staff)/$",
        status_dashboard.status_dashboard,
        name="status_dashboard_tab",
    ),
    # Jumbotron:
    path("jumbotron/", jumbotron.jumbotron, name="jumbotron"),
    path("jumbotron_content/", jumbotron.jumbotron_content, name="jumbotron_content"),
    # Utility functions:
    path("refresh_sidebar_icons/", sidebar.refresh_sidebar_icons, name="refresh_sidebar_icons"),
    re_path(
        r"^refresh_sidebar_icons/" + reservation_item_types + "/$",
        sidebar.refresh_sidebar_icons,
        name="refresh_sidebar_icons",
    ),
    # Facility feedback
    path("feedback/", feedback.feedback, name="feedback"),
    # Facility rules tutorial
    # TODO: this should be removed, since this is really a job for a Learning Management System...
    path("facility_rules_tutorial/", tutorials.facility_rules, name="facility_rules"),
    # Configuration agenda for staff:
    path("configuration_agenda/", configuration_agenda.configuration_agenda, name="configuration_agenda"),
    path(
        "configuration_agenda/near_future/",
        configuration_agenda.configuration_agenda,
        {"time_period": "near_future"},
        name="configuration_agenda_near_future",
    ),
    # Email broadcasts:
    path("get_email_form/", email.get_email_form, name="get_email_form"),
    path("get_email_form_for_user/<int:user_id>/", email.get_email_form_for_user, name="get_email_form_for_user"),
    path("send_email/", email.send_email, name="send_email"),
    path("email_broadcast/", email.email_broadcast, name="email_broadcast"),
    re_path(
        r"^email_broadcast/(?P<audience>tool|area|account|project|project-pis|user|tool-reservation)/$",
        email.email_broadcast,
        name="email_broadcast",
    ),
    path("email_preview/", email.email_preview, name="email_preview"),
    path("compose_email/", email.compose_email, name="compose_email"),
    path("email_export_addresses/", email.export_email_addresses, name="export_email_addresses"),
    path("send_broadcast_email/", email.send_broadcast_email, name="send_broadcast_email"),
    # Maintenance:
    re_path(
        r"^maintenance/(?P<sort_by>urgency|force_shutdown|tool|problem_category|last_updated|creation_time)/$",
        maintenance.maintenance,
        name="maintenance",
    ),
    path("maintenance/", maintenance.maintenance, name="maintenance"),
    path("task_details/<int:task_id>/", maintenance.task_details, name="task_details"),
    # Resources:
    path("resources/", resources.resources, name="resources"),
    path("resources/<int:resource_id>/", resources.resource_details, name="resource_details"),
    path("resources/<int:resource_id>/modify/", resources.modify_resource, name="modify_resource"),
    path("resources/<int:resource_id>/schedule_outage/", resources.schedule_outage, name="schedule_resource_outage"),
    path(
        "resources/<int:resource_id>/delete_scheduled_outage/<int:outage_id>/",
        resources.delete_scheduled_outage,
        name="delete_scheduled_resource_outage",
    ),
    # Consumables:
    path("consumables/", consumables.consumables, name="consumables"),
    path("consumables/<int:index>/remove/", consumables.remove_withdraw_at_index, name="remove_consumable"),
    path("consumables/withdraw/", consumables.make_withdrawals, name="withdraw_consumables"),
    path("consumables/clear/", consumables.clear_withdrawals, name="clear_withdrawals"),
    # Recurring consumable charges
    path("recurring_charges/", consumables.recurring_charges, name="recurring_charges"),
    path("create_recurring_charge/", consumables.create_recurring_charge, name="create_recurring_charge"),
    path(
        "edit_recurring_charge/<int:recurring_charge_id>/",
        consumables.create_recurring_charge,
        name="edit_recurring_charge",
    ),
    path(
        "clear_recurring_charge/<int:recurring_charge_id>/",
        consumables.clear_recurring_charge,
        name="clear_recurring_charge",
    ),
    path(
        "delete_recurring_charge/<int:recurring_charge_id>/",
        consumables.delete_recurring_charge,
        name="delete_recurring_charge",
    ),
    path("export_recurring_charges/", consumables.export_recurring_charges, name="export_recurring_charges"),
    path("search_recurring_charges/", consumables.search_recurring_charges, name="search_recurring_charges"),
    # Training:
    path("training/", training.training, name="training"),
    path("training_entry/", training.training_entry, name="training_entry"),
    path("charge_training/", training.charge_training, name="charge_training"),
    # Safety:
    path("safety/", safety.safety, name="safety"),
    path("safety/items/<int:safety_item_id>/", safety.safety_item, name="safety_item"),
    path("safety/items/search/", safety.safety_items_search, name="safety_items_search"),
    path(
        "safety/items/categories/",
        include(
            [
                path("", safety.safety_categories, name="safety_categories"),
                path("<int:category_id>/", safety.safety_categories, name="safety_categories"),
                path("all_in_one/", safety.safety_all_in_one, name="safety_all_in_one"),
            ]
        ),
    ),
    path("safety/issues/", safety.safety_issues, name="safety_issues"),
    path("safety/issues/create", safety.create_safety_issue, name="create_safety_issue"),
    path("safety/issues/resolved/", safety.resolved_safety_issues, name="resolved_safety_issues"),
    path("safety/issues/<int:ticket_id>/update/", safety.update_safety_issue, name="update_safety_issue"),
    path("safety/safety_data_sheets/", safety.safety_data_sheets, name="safety_data_sheets"),
    path("safety/safety_data_sheets/export/", safety.export_safety_data_sheets, name="export_safety_data_sheets"),
    # For backwards compatibility
    path("safety_data_sheets/", RedirectView.as_view(pattern_name="safety_data_sheets", permanent=True)),
    # Knowledge base
    path("knowledge_base/", knowledge_base.knowledge_base, name="knowledge_base"),
    re_path(
        r"^knowledge_base/(?P<kind>user|staff)/",
        include(
            [
                path("", knowledge_base.knowledge_base, name="knowledge_base"),
                path("items/<int:item_id>/", knowledge_base.knowledge_base_item, name="knowledge_base_item"),
                path("items/search/", knowledge_base.knowledge_base_items_search, name="knowledge_base_items_search"),
                path(
                    "items/categories/",
                    include(
                        [
                            path("", knowledge_base.knowledge_base_categories, name="knowledge_base_categories"),
                            path(
                                "<int:category_id>/",
                                knowledge_base.knowledge_base_categories,
                                name="knowledge_base_categories",
                            ),
                            path(
                                "all_in_one/",
                                knowledge_base.knowledge_base_all_in_one,
                                name="knowledge_base_all_in_one",
                            ),
                        ]
                    ),
                ),
            ]
        ),
    ),
    # Mobile:
    re_path(r"^choose_item/then/(?P<next_page>view_calendar|tool_control)/$", mobile.choose_item, name="choose_item"),
    re_path(
        r"^new_reservation/" + reservation_item_types + "/(?P<item_id>\d+)/$",
        mobile.new_reservation,
        name="new_reservation",
    ),
    re_path(
        r"^new_reservation/"
        + reservation_item_types
        + "/(?P<item_id>\d+)/(?P<date>20\d\d-(0[1-9]|1[012])-(0[1-9]|[12][0-9]|3[01]))/$",
        mobile.new_reservation,
        name="new_reservation",
    ),
    path("make_reservation/", mobile.make_reservation, name="make_reservation"),
    re_path(
        r"^view_calendar/" + reservation_item_types + "/(?P<item_id>\d+)/$", mobile.view_calendar, name="view_calendar"
    ),
    re_path(
        r"^view_calendar/"
        + reservation_item_types
        + "/(?P<item_id>\d+)/(?P<date>20\d\d-(0[1-9]|1[012])-(0[1-9]|[12][0-9]|3[01]))/$",
        mobile.view_calendar,
        name="view_calendar",
    ),
    # Contact staff:
    path("contact_staff/", contact_staff.contact_staff, name="contact_staff"),
    # Area access:
    path("change_project/", area_access.change_project, name="change_project"),
    path("change_project/<int:new_project>/", area_access.change_project, name="change_project"),
    path("calendar_self_log_in/", area_access.calendar_self_login, name="calendar_self_log_in"),
    path("force_area_logout/<int:user_id>/", area_access.force_area_logout, name="force_area_logout"),
    path("self_log_in/", area_access.self_log_in, name="self_log_in"),
    path("self_log_out/<int:user_id>/", area_access.self_log_out, name="self_log_out"),
    # Facility usage:
    path("usage/", usage.usage, name="usage"),
    # Alerts:
    path("alerts/", alerts.alerts, name="alerts"),
    path("delete_alert/<int:alert_id>/", alerts.delete_alert, name="delete_alert"),
    # News:
    path("news/", news.view_recent_news, name="view_recent_news"),
    path("news/archive/", news.view_archived_news, name="view_archived_news"),
    path("news/archive/<int:page>/", news.view_archived_news, name="view_archived_news"),
    path("news/archive_story/<int:story_id>/", news.archive_story, name="archive_story"),
    path("news/new/", news.new_news_form, name="new_news_form"),
    path("news/update/<int:story_id>/", news.news_update_form, name="news_update_form"),
    path("news/publish/", news.publish, name="publish_new_news"),
    path("news/publish/<int:story_id>/", news.publish, name="publish_news_update"),
    # User Preferences
    path("user_preferences/", users.user_preferences, name="user_preferences"),
    # Media
    re_path(
        r"^media/" + MEDIA_PROTECTED + "/(?P<path>.*)$",
        any_staff_required(xframe_options_sameorigin(serve)),
        {"document_root": os.path.join(settings.MEDIA_ROOT, MEDIA_PROTECTED)},
        name="media_protected",
    ),
    re_path(
        r"^media/(?P<path>.*)$",
        login_required(xframe_options_sameorigin(serve)),
        {"document_root": settings.MEDIA_ROOT},
        name="media",
    ),
    re_path(
        r"^media_view/(?P<popup>(true|false))/(?P<content_type_id>\d+)/(?P<document_id>\d+)/$",
        documents.media_view,
        name="media_view",
    ),
    re_path(
        r"^media_list_view/(?P<popup>(true|false))/(?P<allow_zip>(true|false))/$",
        documents.media_list_view,
        name="media_list_view",
    ),
    path("media_zip/", documents.media_zip, name="media_zip"),
    # Favicon
    path(
        "favicon.ico",
        RedirectView.as_view(url=staticfiles_storage.url("favicon.ico")),
    ),
]

if settings.ALLOW_CONDITIONAL_URLS:
    if apps.is_installed("django.contrib.admin"):
        urlpatterns += [path("admin/", admin.site.urls)]

    urlpatterns += [
        # REST API
        path("api/", include(router.urls)),
        path("api/file_import/", api_file_import.file_import, name="api_file_import"),
        # Area access
        path("area_access/", area_access.area_access, name="area_access"),
        path("new_area_access_record/", area_access.new_area_access_record, name="new_area_access_record"),
        # Reminders and periodic events
        path(
            "cancel_unused_reservations/", timed_services.cancel_unused_reservations, name="cancel_unused_reservations"
        ),
        path("create_closure_alerts/", timed_services.create_closure_alerts, name="create_closure_alerts"),
        path(
            "email_out_of_time_reservation_notification/",
            timed_services.email_out_of_time_reservation_notification,
            name="email_out_of_time_reservation_notification",
        ),
        path(
            "email_reservation_ending_reminders/",
            timed_services.email_reservation_ending_reminders,
            name="email_reservation_ending_reminders",
        ),
        path(
            "email_reservation_reminders/",
            timed_services.email_reservation_reminders,
            name="email_reservation_reminders",
        ),
        path(
            "email_scheduled_outage_reminders/",
            timed_services.email_scheduled_outage_reminders,
            name="email_scheduled_outage_reminders",
        ),
        path("email_usage_reminders/", timed_services.email_usage_reminders, name="email_usage_reminders"),
        path(
            "email_weekend_access_notification/",
            timed_services.email_weekend_access_notification,
            name="email_weekend_access_notification",
        ),
        path(
            "email_user_access_expiration_reminders/",
            timed_services.email_user_access_expiration_reminders,
            name="email_user_access_expiration_reminders",
        ),
        path(
            "manage_tool_qualifications/", timed_services.manage_tool_qualifications, name="manage_tool_qualifications"
        ),
        path(
            "deactivate_access_expired_users/",
            timed_services.deactivate_access_expired_users,
            name="deactivate_access_expired_users",
        ),
        path("manage_recurring_charges/", timed_services.manage_recurring_charges, name="manage_recurring_charges"),
        path("auto_logout_users/", timed_services.auto_logout_users, name="auto_logout_users"),
        path(
            "check_and_update_wait_list/", timed_services.check_and_update_wait_list, name="check_and_update_wait_list"
        ),
        # Abuse:
        path("abuse/", abuse.abuse, name="abuse"),
        path("abuse/user_drill_down/", abuse.user_drill_down, name="user_drill_down"),
        # User management:
        path("users/", users.users, name="users"),
        re_path(r"^user/(?P<user_id>\d+|new)/$", users.create_or_modify_user, name="create_or_modify_user"),
        path("users/search/", users.user_search, name="user_search"),
        path("deactivate_user/<int:user_id>/", users.deactivate, name="deactivate_user"),
        path("reset_password/<int:user_id>/", users.reset_password, name="reset_password"),
        path("unlock_account/<int:user_id>/", users.unlock_account, name="unlock_account"),
        # Account & project management:
        path("accounts_and_projects/", accounts_and_projects.accounts_and_projects, name="accounts_and_projects"),
        path("projects/", accounts_and_projects.projects, name="projects"),
        path(
            "project/<int:identifier>/",
            accounts_and_projects.select_accounts_and_projects,
            kwargs={"kind": "project"},
            name="project",
        ),
        path(
            "account/<int:identifier>/",
            accounts_and_projects.select_accounts_and_projects,
            kwargs={"kind": "account"},
            name="account",
        ),
        re_path(
            r"^toggle_active/(?P<kind>account|project)/(?P<identifier>\d+)/$",
            accounts_and_projects.toggle_active,
            name="toggle_active",
        ),
        path("create_project/", accounts_and_projects.create_project, name="create_project"),
        path("create_account/", accounts_and_projects.create_account, name="create_account"),
        path(
            "remove_user_from_project/", accounts_and_projects.remove_user_from_project, name="remove_user_from_project"
        ),
        path("add_user_to_project/", accounts_and_projects.add_user_to_project, name="add_user_to_project"),
        path(
            "projects/<int:project_id>/remove_document/<int:document_id>/",
            accounts_and_projects.remove_document_from_project,
            name="remove_document_from_project",
        ),
        path(
            "projects/<int:project_id>/add_document/",
            accounts_and_projects.add_document_to_project,
            name="add_document_to_project",
        ),
        path("projects/transfer_charges/", accounts_and_projects.transfer_charges, name="transfer_charges"),
        path(
            "projects/search_project_for_transfer/",
            accounts_and_projects.search_project_for_transfer,
            name="search_project_for_transfer",
        ),
        # Account, project, and user history
        re_path(r"^history/(?P<item_type>account|project|user)/(?P<item_id>\d+)/$", history.history, name="history"),
        # Site customization:
        path("customization/", customization.customization, name="customization"),
        path("customization/<str:key>/", customization.customization, name="customization"),
        path("customize/<str:key>/", customization.customize, name="customize"),
        path("customize/<str:key>/<str:element>/", customization.customize, name="customize"),
        # Project usage:
        path("project_usage/", usage.project_usage, name="project_usage"),
        path("project_billing/", usage.project_billing, name="project_billing"),
        # Staff absence
        path("create_staff_absence/", status_dashboard.create_staff_absence, name="create_staff_absence"),
        path("edit_staff_absence/<int:absence_id>/", status_dashboard.create_staff_absence, name="edit_staff_absence"),
        path(
            "delete_staff_absence/<int:absence_id>/", status_dashboard.delete_staff_absence, name="delete_staff_absence"
        ),
        # Tool credentials
        path("tool_credentials/", tool_credentials.tool_credentials_list, name="tool_credentials"),
        path("tool_credentials/export/", tool_credentials.export_tool_credentials, name="export_tool_credentials"),
        # Billing:
        path("billing/", usage.billing, name="billing"),
    ]


if settings.DEBUG:
    # Static files
    re_path(r"^static/(?P<path>.*$)", serve, {"document_root": settings.STATIC_ROOT}, name="static"),

    if apps.is_installed("debug_toolbar"):
        urlpatterns += [
            path("__debug__/", include("debug_toolbar.urls")),
        ]
