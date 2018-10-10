from django.conf import settings
from django.conf.urls import include, url
from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.views.static import serve
from rest_framework import routers

from NEMO.views import abuse, accounts_and_projects, alerts, api, area_access, authentication, calendar, configuration_agenda, consumables, contact_staff, customization, email, feedback, get_projects, history, jumbotron, kiosk, landing, maintenance, mobile, usage, news, qualifications, remote_work, resources, safety, sidebar, staff_charges, status_dashboard, tasks, tool_control, training, tutorials, users

# Use our custom login page instead of Django's built-in one.
admin.site.login = login_required(admin.site.login)

# REST API URLs
router = routers.DefaultRouter()
router.register(r'users', api.UserViewSet)
router.register(r'projects', api.ProjectViewSet)
router.register(r'accounts', api.AccountViewSet)
router.register(r'tools', api.ToolViewSet)
router.register(r'reservations', api.ReservationViewSet)
router.register(r'usage_events', api.UsageEventViewSet)
router.register(r'area_access_records', api.AreaAccessRecordViewSet)
router.register(r'tasks', api.TaskViewSet)
router.register(r'scheduled_outages', api.ScheduledOutageViewSet)

urlpatterns = [
	# Authentication & error pages:
	url(r'^login/$', authentication.login_user, name='login'),
	url(r'^logout/$', authentication.logout_user, name='logout'),

	# Root URL defaults to the calendar page on desktop systems, and the mobile homepage for mobile devices:
	url(r'^$', landing.landing, name='landing'),

	# Get a list of projects for a user:
	url(r'^get_projects/$', get_projects.get_projects, name='get_projects'),
	url(r'^get_projects_for_tool_control/$', get_projects.get_projects_for_tool_control, name='get_projects_for_tool_control'),
	url(r'^get_projects_for_self/$', get_projects.get_projects_for_self, name='get_projects_for_self'),

	# Tool control:
	url(r'^tool_control/(?P<tool_id>\d+)/$', tool_control.tool_control, name='tool_control'),
	url(r'^tool_control/$', tool_control.tool_control, name='tool_control'),
	url(r'^tool_status/(?P<tool_id>\d+)/$', tool_control.tool_status, name='tool_status'),
	url(r'^use_tool_for_other/$', tool_control.use_tool_for_other, name='use_tool_for_other'),
	url(r'^tool_configuration/$', tool_control.tool_configuration, name='tool_configuration'),
	url(r'^create_comment/$', tool_control.create_comment, name='create_comment'),
	url(r'^hide_comment/(?P<comment_id>\d+)/$', tool_control.hide_comment, name='hide_comment'),
	url(r'^enable_tool/(?P<tool_id>\d+)/user/(?P<user_id>\d+)/project/(?P<project_id>\d+)/staff_charge/(?P<staff_charge>(true|false))/$', tool_control.enable_tool, name='enable_tool'),
	url(r'^disable_tool/(?P<tool_id>\d+)/$', tool_control.disable_tool, name='disable_tool'),
	url(r'^past_comments_and_tasks/$', tool_control.past_comments_and_tasks, name='past_comments_and_tasks'),
	url(r'^ten_most_recent_past_comments_and_tasks/(?P<tool_id>\d+)/$', tool_control.ten_most_recent_past_comments_and_tasks, name='ten_most_recent_past_comments_and_tasks'),

	# Tasks:
	url(r'^create_task/$', tasks.create, name='create_task'),
	url(r'^cancel_task/(?P<task_id>\d+)/$', tasks.cancel, name='cancel_task'),
	url(r'^update_task/(?P<task_id>\d+)/$', tasks.update, name='update_task'),
	url(r'^task_update_form/(?P<task_id>\d+)/$', tasks.task_update_form, name='task_update_form'),
	url(r'^task_resolution_form/(?P<task_id>\d+)/$', tasks.task_resolution_form, name='task_resolution_form'),

	# Calendar:
	url(r'^calendar/(?P<tool_id>\d+)/$', calendar.calendar, name='calendar'),
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

	# Jumbotron:
	url(r'^jumbotron/$', jumbotron.jumbotron, name='jumbotron'),
	url(r'^jumbotron_content/$', jumbotron.jumbotron_content, name='jumbotron_content'),

	# Utility functions:
	url(r'^refresh_sidebar_icons/$', sidebar.refresh_sidebar_icons, name='refresh_sidebar_icons'),

	# NanoFab feedback
	url(r'^feedback/$', feedback.feedback, name='feedback'),

	# NanoFab rules tutorial
	# TODO: this should be removed, since this is really a job for a Learning Management System...
	url(r'^nanofab_rules_tutorial/$', tutorials.nanofab_rules, name='nanofab_rules'),

	# Configuration agenda for staff:
	url(r'^configuration_agenda/$', configuration_agenda.configuration_agenda, name='configuration_agenda'),
	url(r'^configuration_agenda/near_future/$', configuration_agenda.configuration_agenda, {'time_period': 'near_future'}, name='configuration_agenda_near_future'),

	# Email broadcasts:
	url(r'^get_email_form/$', email.get_email_form, name='get_email_form'),
	url(r'^get_email_form_for_user/(?P<user_id>\d+)/$', email.get_email_form_for_user, name='get_email_form_for_user'),
	url(r'^send_email/$', email.send_email, name='send_email'),
	url(r'^email_broadcast/$', email.email_broadcast, name='email_broadcast'),
	url(r'^email_broadcast/(?P<audience>tool|account|project)/$', email.email_broadcast, name='email_broadcast'),
	url(r'^compose_email/$', email.compose_email, name='compose_email'),
	url(r'^send_broadcast_email/$', email.send_broadcast_email, name='send_broadcast_email'),

	# Maintenance:
	url(r'^maintenance/(?P<sort_by>urgency|force_shutdown|tool|problem_category|last_updated|creation_time)/$', maintenance.maintenance, name='maintenance'),
	url(r'^maintenance/$', maintenance.maintenance, name='maintenance'),
	url(r'^task_details/(?P<task_id>\d+)/$', maintenance.task_details, name='task_details'),

	# Resources:
	url(r'^resources/$', resources.resources, name='resources'),
	url(r'^resources/modify/(?P<resource_id>\d+)/$', resources.modify_resource, name='modify_resource'),
	url(r'^resources/schedule_outage/$', resources.schedule_outage, name='schedule_resource_outage'),
	url(r'^resources/delete_scheduled_outage/(?P<outage_id>\d+)/$', resources.delete_scheduled_outage, name='delete_scheduled_resource_outage'),

	# Consumables:
	url(r'^consumables/$', consumables.consumables, name='consumables'),

	# Training:
	url(r'^training/$', training.training, name='training'),
	url(r'^training_entry/$', training.training_entry, name='training_entry'),
	url(r'^charge_training/$', training.charge_training, name='charge_training'),

	# Safety:
	url(r'^safety/$', safety.safety, name='safety'),
	url(r'^safety/resolved$', safety.resolved_safety_issues, name='resolved_safety_issues'),
	url(r'^safety/update/(?P<ticket_id>\d+)/$', safety.update_safety_issue, name='update_safety_issue'),

	# Mobile:
	url(r'^choose_tool/then/(?P<next_page>view_calendar|tool_control)/$', mobile.choose_tool, name='choose_tool'),
	url(r'^new_reservation/(?P<tool_id>\d+)/$', mobile.new_reservation, name='new_reservation'),
	url(r'^new_reservation/(?P<tool_id>\d+)/(?P<date>20\d\d-(0[1-9]|1[012])-(0[1-9]|[12][0-9]|3[01]))/$', mobile.new_reservation, name='new_reservation'),
	url(r'^make_reservation/$', mobile.make_reservation, name='make_reservation'),
	url(r'^view_calendar/(?P<tool_id>\d+)/$', mobile.view_calendar, name='view_calendar'),
	url(r'^view_calendar/(?P<tool_id>\d+)/(?P<date>20\d\d-(0[1-9]|1[012])-(0[1-9]|[12][0-9]|3[01]))/$', mobile.view_calendar, name='view_calendar'),

	# Contact staff:
	url(r'^contact_staff/$', contact_staff.contact_staff, name='contact_staff'),

	# Area access:
	url(r'^change_project/$', area_access.change_project, name='change_project'),
	url(r'^change_project/(?P<new_project>\d+)/$', area_access.change_project, name='change_project'),
	url(r'^force_area_logout/(?P<user_id>\d+)/$', area_access.force_area_logout, name='force_area_logout'),

	# NanoFab usage:
	url(r'^usage/$', usage.usage, name='usage'),
	url(r'^billing_information/(?P<timeframe>.*)/$', usage.billing_information, name='billing_information'),

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
]

if settings.ALLOW_CONDITIONAL_URLS:
	urlpatterns += [
		url(r'^admin/', include(admin.site.urls)),
		url(r'^api/', include(router.urls)),

		# Tablet area access
		url(r'^welcome_screen/(?P<door_id>\d+)/$', area_access.welcome_screen, name='welcome_screen'),
		url(r'^farewell_screen/(?P<door_id>\d+)/$', area_access.farewell_screen, name='farewell_screen'),
		url(r'^login_to_area/(?P<door_id>\d+)/$', area_access.login_to_area, name='login_to_area'),
		url(r'^logout_of_area/(?P<door_id>\d+)/$', area_access.logout_of_area, name='logout_of_area'),
		url(r'^open_door/(?P<door_id>\d+)/$', area_access.open_door, name='open_door'),

		# Tablet kiosk
		url(r'^kiosk/enable_tool/$', kiosk.enable_tool, name='enable_tool_from_kiosk'),
		url(r'^kiosk/disable_tool/$', kiosk.disable_tool, name='disable_tool_from_kiosk'),
		url(r'^kiosk/choices/$', kiosk.choices, name='kiosk_choices'),
		url(r'^kiosk/category_choices/(?P<category>.+)/(?P<user_id>\d+)/$', kiosk.category_choices, name='kiosk_category_choices'),
		url(r'^kiosk/tool_information/(?P<tool_id>\d+)/(?P<user_id>\d+)/(?P<back>back_to_start|back_to_category)/$', kiosk.tool_information, name='kiosk_tool_information'),
		url(r'^kiosk/(?P<location>.+)/$', kiosk.kiosk, name='kiosk'),
		url(r'^kiosk/$', kiosk.kiosk, name='kiosk'),

		# Area access
		url(r'^area_access/$', area_access.area_access, name='area_access'),
		url(r'^new_area_access_record/$', area_access.new_area_access_record, name='new_area_access_record'),

		# Reminders and periodic events
		url(r'^email_reservation_reminders/$', calendar.email_reservation_reminders, name='email_reservation_reminders'),
		url(r'^email_usage_reminders/$', calendar.email_usage_reminders, name='email_usage_reminders'),
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
		url(r'^project/(?P<identifier>\d+)/$', accounts_and_projects.accounts_and_projects, kwargs={'kind': 'project'}, name='project'),
		url(r'^account/(?P<identifier>\d+)/$', accounts_and_projects.accounts_and_projects, kwargs={'kind': 'account'}, name='account'),
		url(r'^toggle_active/(?P<kind>account|project)/(?P<identifier>\d+)/$', accounts_and_projects.toggle_active, name='toggle_active'),
		url(r'^create_project/$', accounts_and_projects.create_project, name='create_project'),
		url(r'^create_account/$', accounts_and_projects.create_account, name='create_account'),
		url(r'^remove_user/(?P<user_id>\d+)/from_project/(?P<project_id>\d+)/$', accounts_and_projects.remove_user_from_project, name='remove_user_from_project'),
		url(r'^add_user/(?P<user_id>\d+)/to_project/(?P<project_id>\d+)/$', accounts_and_projects.add_user_to_project, name='add_user_to_project'),

		# Account, project, and user history
		url(r'^history/(?P<item_type>account|project|user)/(?P<item_id>\d+)/$', history.history, name='history'),

		# Remote work:
		url(r'^remote_work/$', remote_work.remote_work, name='remote_work'),
		url(r'^validate_staff_charge/(?P<staff_charge_id>\d+)/$', remote_work.validate_staff_charge, name='validate_staff_charge'),
		url(r'^validate_usage_event/(?P<usage_event_id>\d+)/$', remote_work.validate_usage_event, name='validate_usage_event'),

		# Site customization:
		url(r'^customization/$', customization.customization, name='customization'),
		url(r'^customize/(?P<element>.+)/$', customization.customize, name='customize'),
	]

if settings.DEBUG:
	# Static files
	url(r'^static/(?P<path>.*$)', serve, {'document_root': settings.STATIC_ROOT}, name='static'),

	try:
		# Django debug toolbar
		import debug_toolbar
		urlpatterns += [
			url(r'^__debug__/', include(debug_toolbar.urls)),
		]
	except ImportError:
		pass
