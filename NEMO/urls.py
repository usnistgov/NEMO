import logging
from importlib import import_module

from django.apps import apps
from django.conf import settings
from django.conf.urls import include, url
from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LogoutView
from django.urls import path
from django.views.static import serve
from rest_framework import routers

from NEMO.models import ReservationItemType
from NEMO.views import abuse, accounts_and_projects, alerts, api, area_access, authentication, calendar, configuration_agenda, consumables, contact_staff, customization, email, feedback, get_projects, history, jumbotron, landing, maintenance, mobile, usage, news, qualifications, remote_work, resources, safety, sidebar, staff_charges, status_dashboard, tasks, tool_control, training, tutorials, users, buddy_system

logger = logging.getLogger(__name__)

if apps.is_installed("django.contrib.admin"):
	# Use our custom login page instead of Django's built-in one.
	admin.site.login = login_required(admin.site.login)

# REST API URLs
router = routers.DefaultRouter()
router.register(r'accounts', api.AccountViewSet)
router.register(r'area_access_records', api.AreaAccessRecordViewSet)
router.register(r'areas', api.AreaViewSet)
router.register(r'projects', api.ProjectViewSet)
router.register(r'reservations', api.ReservationViewSet)
router.register(r'resources', api.ResourceViewSet)
router.register(r'scheduled_outages', api.ScheduledOutageViewSet)
router.register(r'staff_charges', api.StaffChargeViewSet)
router.register(r'tasks', api.TaskViewSet)
router.register(r'tools', api.ToolViewSet)
router.register(r'training_sessions', api.TrainingSessionViewSet)
router.register(r'usage_events', api.UsageEventViewSet)
router.register(r'users', api.UserViewSet)

reservation_item_types = f'(?P<item_type>{"|".join(ReservationItemType.values())})'

urlpatterns = []

# Include urls for all NEMO plugins (that start with prefix NEMO)
# URLs in plugins with exact same path will take precedence over regular NEMO URLs
# Note that the path MUST be the same, down to the last "/"
for app in apps.get_app_configs():
	app_name = app.name
	if app_name != 'NEMO' and app_name.startswith('NEMO'):
		try:
			mod = import_module('%s.urls' % app_name)
		except ModuleNotFoundError:
			logger.warning(f"no urls found for NEMO plugin: {app_name}")
			pass
		except Exception as e:
			logger.warning(f"could not import urls for NEMO plugin: {app_name} {str(e)}")
			pass
		else:
			urlpatterns += [path('', include('%s.urls' % app_name))]
			logger.debug(f"automatically including urls for plugin: {app_name}")

urlpatterns += [
	# Authentication & error pages:
	url(r'^login/$', authentication.login_user, name='login'),
	url(r'^logout/$', LogoutView.as_view(next_page = 'landing' if not settings.LOGOUT_REDIRECT_URL else None), name='logout'),
	url(r'^impersonate/$', authentication.impersonate, name='impersonate'),
	url(r'^authorization_failed/$', authentication.authorization_failed, name='authorization_failed'),

	# Root URL defaults to the calendar page on desktop systems, and the mobile homepage for mobile devices:
	url(r'^$', landing.landing, name='landing'),

	# Get a list of projects for a user:
	url(r'^get_projects/$', get_projects.get_projects, name='get_projects'),
	url(r'^get_projects_for_tool_control/$', get_projects.get_projects_for_tool_control, name='get_projects_for_tool_control'),
	url(r'^get_projects_for_self/$', get_projects.get_projects_for_self, name='get_projects_for_self'),

	# Tool control:
	# This tool_control URL is needed to be able to reverse when choosing items on mobile using next_page. (see choose_item.html for details)
	url(r'^tool_control/(?P<item_type>(tool))/(?P<tool_id>\d+)/$', tool_control.tool_control, name='tool_control'),
	url(r'^tool_control/(?P<tool_id>\d+)/$', tool_control.tool_control, name='tool_control'),
	url(r'^tool_control/$', tool_control.tool_control, name='tool_control'),
	url(r'^tool_status/(?P<tool_id>\d+)/$', tool_control.tool_status, name='tool_status'),
	url(r'^use_tool_for_other/$', tool_control.use_tool_for_other, name='use_tool_for_other'),
	url(r'^tool_configuration/$', tool_control.tool_configuration, name='tool_configuration'),
	url(r'^create_comment/$', tool_control.create_comment, name='create_comment'),
	url(r'^hide_comment/(?P<comment_id>\d+)/$', tool_control.hide_comment, name='hide_comment'),
	url(r'^enable_tool/(?P<tool_id>\d+)/user/(?P<user_id>\d+)/project/(?P<project_id>\d+)/staff_charge/(?P<staff_charge>(true|false))/$', tool_control.enable_tool, name='enable_tool'),
	url(r'^disable_tool/(?P<tool_id>\d+)/$', tool_control.disable_tool, name='disable_tool'),
	url(r'^usage_data_history/(?P<tool_id>\d+)/$', tool_control.usage_data_history, name='usage_data_history'),
	url(r'^past_comments_and_tasks/$', tool_control.past_comments_and_tasks, name='past_comments_and_tasks'),
	url(r'^ten_most_recent_past_comments_and_tasks/(?P<tool_id>\d+)/$', tool_control.ten_most_recent_past_comments_and_tasks, name='ten_most_recent_past_comments_and_tasks'),
	url(r'^tool_usage_group_question/(?P<tool_id>\d+)/(?P<group_name>\w+)/$', tool_control.tool_usage_group_question, name='tool_usage_group_question'),
	url(r'^reset_tool_counter/(?P<counter_id>\d+)/$', tool_control.reset_tool_counter, name='reset_tool_counter'),

	# Buddy System
	url(r'^buddy_system/$', buddy_system.buddy_system, name='buddy_system'),
	url(r'^create_buddy_request/$', buddy_system.create_buddy_request, name='create_buddy_request'),
	url(r'^edit_buddy_request/(?P<request_id>\d+)/$', buddy_system.create_buddy_request, name='edit_buddy_request'),
	url(r'^delete_buddy_request/(?P<request_id>\d+)/$', buddy_system.delete_buddy_request, name='delete_buddy_request'),
	url(r'^buddy_request_reply/(?P<request_id>\d+)/$', buddy_system.buddy_request_reply, name='buddy_request_reply'),

	# Tasks:
	url(r'^create_task/$', tasks.create, name='create_task'),
	url(r'^cancel_task/(?P<task_id>\d+)/$', tasks.cancel, name='cancel_task'),
	url(r'^update_task/(?P<task_id>\d+)/$', tasks.update, name='update_task'),
	url(r'^task_update_form/(?P<task_id>\d+)/$', tasks.task_update_form, name='task_update_form'),
	url(r'^task_resolution_form/(?P<task_id>\d+)/$', tasks.task_resolution_form, name='task_resolution_form'),

	# Calendar:
	url(r'^calendar/'+ reservation_item_types + '/(?P<item_id>\d+)/$', calendar.calendar, name='calendar'),
	url(r'^calendar/$', calendar.calendar, name='calendar'),
	url(r'^event_feed/$', calendar.event_feed, name='event_feed'),
	url(r'^create_reservation/$', calendar.create_reservation, name='create_reservation'),
	url(r'^create_outage/$', calendar.create_outage, name='create_outage'),
	url(r'^resize_reservation/$', calendar.resize_reservation, name='resize_reservation'),
	url(r'^resize_outage/$', calendar.resize_outage, name='resize_outage'),
	url(r'^move_reservation/$', calendar.move_reservation, name='move_reservation'),
	url(r'^move_outage/$', calendar.move_outage, name='move_outage'),
	url(r'^cancel_reservation/(?P<reservation_id>\d+)/$', calendar.cancel_reservation, name='cancel_reservation'),
	url(r'^cancel_outage/(?P<outage_id>\d+)/$', calendar.cancel_outage, name='cancel_outage'),
	url(r'^set_reservation_title/(?P<reservation_id>\d+)/$', calendar.set_reservation_title, name='set_reservation_title'),
	url(r'^change_reservation_project/(?P<reservation_id>\d+)/$', calendar.change_reservation_project, name='change_reservation_project'),
	url(r'^event_details/reservation/(?P<reservation_id>\d+)/$', calendar.reservation_details, name='reservation_details'),
	url(r'^event_details/outage/(?P<outage_id>\d+)/$', calendar.outage_details, name='outage_details'),
	url(r'^event_details/usage/(?P<event_id>\d+)/$', calendar.usage_details, name='usage_details'),
	url(r'^event_details/area_access/(?P<event_id>\d+)/$', calendar.area_access_details, name='area_access_details'),
	url(r'^proxy_reservation/$', calendar.proxy_reservation, name='proxy_reservation'),

	# Qualifications:
	url(r'^qualifications/$', qualifications.qualifications, name='qualifications'),
	url(r'^modify_qualifications/$', qualifications.modify_qualifications, name='modify_qualifications'),
	url(r'^get_qualified_users/$', qualifications.get_qualified_users, name='get_qualified_users'),

	# Staff charges:
	url(r'^staff_charges/$', staff_charges.staff_charges, name='staff_charges'),
	url(r'^begin_staff_charge/$', staff_charges.begin_staff_charge, name='begin_staff_charge'),
	url(r'^end_staff_charge/$', staff_charges.end_staff_charge, name='end_staff_charge'),
	url(r'^begin_staff_area_charge/$', staff_charges.begin_staff_area_charge, name='begin_staff_area_charge'),
	url(r'^end_staff_area_charge/$', staff_charges.end_staff_area_charge, name='end_staff_area_charge'),

	# Status dashboard:
	url(r'^status_dashboard/$', status_dashboard.status_dashboard, name='status_dashboard'),
	url(r'^status_dashboard/(?P<tab>tools|occupancy)/$', status_dashboard.status_dashboard, name='status_dashboard_tab'),

	# Jumbotron:
	url(r'^jumbotron/$', jumbotron.jumbotron, name='jumbotron'),
	url(r'^jumbotron_content/$', jumbotron.jumbotron_content, name='jumbotron_content'),

	# Utility functions:
	url(r'^refresh_sidebar_icons/$', sidebar.refresh_sidebar_icons, name='refresh_sidebar_icons'),
	url(r'^refresh_sidebar_icons/'+reservation_item_types+'/$', sidebar.refresh_sidebar_icons, name='refresh_sidebar_icons'),

	# Facility feedback
	url(r'^feedback/$', feedback.feedback, name='feedback'),

	# Facility rules tutorial
	# TODO: this should be removed, since this is really a job for a Learning Management System...
	url(r'^facility_rules_tutorial/$', tutorials.facility_rules, name='facility_rules'),

	# Configuration agenda for staff:
	url(r'^configuration_agenda/$', configuration_agenda.configuration_agenda, name='configuration_agenda'),
	url(r'^configuration_agenda/near_future/$', configuration_agenda.configuration_agenda, {'time_period': 'near_future'}, name='configuration_agenda_near_future'),

	# Email broadcasts:
	url(r'^get_email_form/$', email.get_email_form, name='get_email_form'),
	url(r'^get_email_form_for_user/(?P<user_id>\d+)/$', email.get_email_form_for_user, name='get_email_form_for_user'),
	url(r'^send_email/$', email.send_email, name='send_email'),
	url(r'^email_broadcast/$', email.email_broadcast, name='email_broadcast'),
	url(r'^email_broadcast/(?P<audience>tool|area|account|project)/$', email.email_broadcast, name='email_broadcast'),
	url(r'^email_preview/$', email.email_preview, name='email_preview'),
	url(r'^compose_email/$', email.compose_email, name='compose_email'),
	url(r'^send_broadcast_email/$', email.send_broadcast_email, name='send_broadcast_email'),

	# Maintenance:
	url(r'^maintenance/(?P<sort_by>urgency|force_shutdown|tool|problem_category|last_updated|creation_time)/$', maintenance.maintenance, name='maintenance'),
	url(r'^maintenance/$', maintenance.maintenance, name='maintenance'),
	url(r'^task_details/(?P<task_id>\d+)/$', maintenance.task_details, name='task_details'),

	# Resources:
	url(r'^resources/$', resources.resources, name='resources'),
	url(r'^resources/(?P<resource_id>\d+)/$', resources.resource_details, name='resource_details'),
	url(r'^resources/(?P<resource_id>\d+)/modify/$', resources.modify_resource, name='modify_resource'),
	url(r'^resources/(?P<resource_id>\d+)/schedule_outage/$', resources.schedule_outage, name='schedule_resource_outage'),
	url(r'^resources/(?P<resource_id>\d+)/delete_scheduled_outage/(?P<outage_id>\d+)/$', resources.delete_scheduled_outage, name='delete_scheduled_resource_outage'),

	# Consumables:
	url(r'^consumables/$', consumables.consumables, name='consumables'),
	url(r'^consumables/(?P<index>\d+)/remove$', consumables.remove_withdraw_at_index, name='remove_consumable'),
	url(r'^consumables/withdraw$', consumables.make_withdrawals, name='withdraw_consumables'),
	url(r'^consumables/clear$', consumables.clear_withdrawals, name='clear_withdrawals'),

	# Training:
	url(r'^training/$', training.training, name='training'),
	url(r'^training_entry/$', training.training_entry, name='training_entry'),
	url(r'^charge_training/$', training.charge_training, name='charge_training'),

	# Safety:
	url(r'^safety/$', safety.safety, name='safety'),
	url(r'^safety/resolved$', safety.resolved_safety_issues, name='resolved_safety_issues'),
	url(r'^safety/update/(?P<ticket_id>\d+)/$', safety.update_safety_issue, name='update_safety_issue'),

	# Mobile:
	url(r'^choose_item/then/(?P<next_page>view_calendar|tool_control)/$', mobile.choose_item, name='choose_item'),
	url(r'^new_reservation/'+reservation_item_types+'/(?P<item_id>\d+)/$', mobile.new_reservation, name='new_reservation'),
	url(r'^new_reservation/'+reservation_item_types+'/(?P<item_id>\d+)/(?P<date>20\d\d-(0[1-9]|1[012])-(0[1-9]|[12][0-9]|3[01]))/$', mobile.new_reservation, name='new_reservation'),
	url(r'^make_reservation/$', mobile.make_reservation, name='make_reservation'),
	url(r'^view_calendar/'+reservation_item_types+'/(?P<item_id>\d+)/$', mobile.view_calendar, name='view_calendar'),
	url(r'^view_calendar/'+reservation_item_types+'/(?P<item_id>\d+)/(?P<date>20\d\d-(0[1-9]|1[012])-(0[1-9]|[12][0-9]|3[01]))/$', mobile.view_calendar, name='view_calendar'),

	# Contact staff:
	url(r'^contact_staff/$', contact_staff.contact_staff, name='contact_staff'),

	# Area access:
	url(r'^change_project/$', area_access.change_project, name='change_project'),
	url(r'^change_project/(?P<new_project>\d+)/$', area_access.change_project, name='change_project'),
	url(r'^force_area_logout/(?P<user_id>\d+)/$', area_access.force_area_logout, name='force_area_logout'),
	url(r'^calendar_self_log_in/$', area_access.calendar_self_login, name='calendar_self_log_in'),
	url(r'^self_log_in/$', area_access.self_log_in, name='self_log_in'),
	url(r'^self_log_out/(?P<user_id>\d+)$', area_access.self_log_out, name='self_log_out'),

	# Facility usage:
	url(r'^usage/$', usage.usage, name='usage'),

	# Alerts:
	url(r'^alerts/$', alerts.alerts, name='alerts'),
	url(r'^delete_alert/(?P<alert_id>\d+)/$', alerts.delete_alert, name='delete_alert'),

	# News:
	url(r'^news/$', news.view_recent_news, name='view_recent_news'),
	url(r'^news/archive/$', news.view_archived_news, name='view_archived_news'),
	url(r'^news/archive/(?P<page>\d+)/$', news.view_archived_news, name='view_archived_news'),
	url(r'^news/archive_story/(?P<story_id>\d+)/$', news.archive_story, name='archive_story'),
	url(r'^news/new/$', news.new_news_form, name='new_news_form'),
	url(r'^news/update/(?P<story_id>\d+)/$', news.news_update_form, name='news_update_form'),
	url(r'^news/publish/$', news.publish, name='publish_new_news'),
	url(r'^news/publish/(?P<story_id>\d+)/$', news.publish, name='publish_news_update'),

	# Media
	url(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}, name='media'),

	# User Preferences
	url(r'^user_preferences/$', users.user_preferences, name='user_preferences')
]

if settings.ALLOW_CONDITIONAL_URLS:
	urlpatterns += [
		url(r'^admin/', admin.site.urls),

		# REST API
		url(r'^api/', include(router.urls)),
		url(r'^api/billing/?$', api.billing),

		# Area access
		url(r'^area_access/$', area_access.area_access, name='area_access'),
		url(r'^new_area_access_record/$', area_access.new_area_access_record, name='new_area_access_record'),

		# Reminders and periodic events
		url(r'^email_reservation_reminders/$', calendar.email_reservation_reminders, name='email_reservation_reminders'),
		url(r'^email_reservation_ending_reminders/$', calendar.email_reservation_ending_reminders, name='email_reservation_ending_reminders'),
		url(r'^email_usage_reminders/$', calendar.email_usage_reminders, name='email_usage_reminders'),
		url(r'^email_out_of_time_reservation_notification/$', calendar.email_out_of_time_reservation_notification, name='email_out_of_time_reservation_notification'),
		url(r'^cancel_unused_reservations/$', calendar.cancel_unused_reservations, name='cancel_unused_reservations'),

		# Abuse:
		url(r'^abuse/$', abuse.abuse, name='abuse'),
		url(r'^abuse/user_drill_down/$', abuse.user_drill_down, name='user_drill_down'),

		# User management:
		url(r'^users/$', users.users, name='users'),
		url(r'^user/(?P<user_id>\d+|new)/', users.create_or_modify_user, name='create_or_modify_user'),
		url(r'^deactivate_user/(?P<user_id>\d+)/', users.deactivate, name='deactivate_user'),
		url(r'^reset_password/(?P<user_id>\d+)/$', users.reset_password, name='reset_password'),
		url(r'^unlock_account/(?P<user_id>\d+)/$', users.unlock_account, name='unlock_account'),

		# Account & project management:
		url(r'^accounts_and_projects/$', accounts_and_projects.accounts_and_projects, name='accounts_and_projects'),
		url(r'^projects/$', accounts_and_projects.projects, name='projects'),
		url(r'^project/(?P<identifier>\d+)/$', accounts_and_projects.select_accounts_and_projects, kwargs={'kind': 'project'}, name='project'),
		url(r'^account/(?P<identifier>\d+)/$', accounts_and_projects.select_accounts_and_projects, kwargs={'kind': 'account'}, name='account'),
		url(r'^toggle_active/(?P<kind>account|project)/(?P<identifier>\d+)/$', accounts_and_projects.toggle_active, name='toggle_active'),
		url(r'^create_project/$', accounts_and_projects.create_project, name='create_project'),
		url(r'^create_account/$', accounts_and_projects.create_account, name='create_account'),
		url(r'^remove_user_from_project/$', accounts_and_projects.remove_user_from_project, name='remove_user_from_project'),
		url(r'^add_user_to_project/$', accounts_and_projects.add_user_to_project, name='add_user_to_project'),

		# Account, project, and user history
		url(r'^history/(?P<item_type>account|project|user)/(?P<item_id>\d+)/$', history.history, name='history'),

		# Remote work:
		url(r'^remote_work/$', remote_work.remote_work, name='remote_work'),
		url(r'^validate_staff_charge/(?P<staff_charge_id>\d+)/$', remote_work.validate_staff_charge, name='validate_staff_charge'),
		url(r'^validate_usage_event/(?P<usage_event_id>\d+)/$', remote_work.validate_usage_event, name='validate_usage_event'),

		# Site customization:
		url(r'^customization/$', customization.customization, name='customization'),
		url(r'^customize/(?P<element>.+)/$', customization.customize, name='customize'),

		# Project Usage:
		url(r'^project_usage/$', usage.project_usage, name='project_usage'),
		url(r'^project_billing/$', usage.project_billing, name='project_billing'),

		# Billing:
		url(r'^billing/$', usage.billing, name='billing'),
	]


if settings.DEBUG:
	# Static files
	url(r'^static/(?P<path>.*$)', serve, {'document_root': settings.STATIC_ROOT}, name='static'),

	if apps.is_installed('debug_toolbar'):
		urlpatterns += [
			url(r'^__debug__/', include('debug_toolbar.urls')),
		]
