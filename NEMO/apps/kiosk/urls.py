from django.urls import include, path, re_path
from NEMO.apps.kiosk import views
from NEMO.views import area_access, status_dashboard

urlpatterns = [
    # Tablet kiosk
    path(
        "kiosk/",
        include(
            [
                path("occupancy/", area_access.occupancy, name="kiosk_occupancy"),
                path("kiosk_usage/", status_dashboard.status_dashboard, name="kiosk_usage"),
                path("kiosk_alerts/", status_dashboard.get_alerts, name="kiosk_alerts"),
                path("enable_tool/", views.enable_tool, name="enable_tool_from_kiosk"),
                path("disable_tool/", views.disable_tool, name="disable_tool_from_kiosk"),
                path("reserve_tool/", views.reserve_tool, name="reserve_tool_from_kiosk"),
                path("post_comment/", views.post_comment, name="post_comment_from_kiosk"),
                path("report_problem/", views.report_problem, name="report_problem_from_kiosk"),
                path(
                    "cancel_reservation/<int:reservation_id>/",
                    views.cancel_reservation,
                    name="cancel_reservation_from_kiosk",
                ),
                path("choices/", views.choices, name="kiosk_choices"),
                path(
                    "category_choices/<path:category>/<int:user_id>/",
                    views.category_choices,
                    name="kiosk_category_choices",
                ),
                re_path(
                    r"^tool_information/(?P<tool_id>\d+)/(?P<user_id>\d+)/(?P<back>back_to_start|back_to_category)/$",
                    views.tool_information,
                    name="kiosk_tool_information",
                ),
                re_path(
                    r"^tool_reservation/(?P<tool_id>\d+)/(?P<user_id>\d+)/(?P<back>back_to_start|back_to_category)/$",
                    views.tool_reservation,
                    name="kiosk_tool_reservation",
                ),
                path("tool_configuration/", views.kiosk_tool_configuration, name="kiosk_tool_configuration"),
                path("enter_wait_list/", views.enter_wait_list, name="enter_wait_list_from_kiosk"),
                path("exit_wait_list/", views.exit_wait_list, name="exit_wait_list_from_kiosk"),
                path("logout_user/<int:tool_id>", views.logout_user, name="kiosk_logout_user"),
                path("checkout/<int:customer_id>", views.checkout, name="kiosk_checkout"),
                path("clear_withdrawals", views.clear_withdrawals, name="kiosk_clear_withdrawals"),
                path("withdraw_consumables", views.make_withdrawals, name="kiosk_withdraw_consumables"),
                path("remove_consumable", views.remove_withdraw_at_index, name="kiosk_remove_consumable"),
                path(
                    "get_projects_for_consumables",
                    views.get_projects_for_consumables,
                    name="get_projects_for_consumables_kiosk",
                ),
                re_path(
                    r"^tool_report_problem/(?P<tool_id>\d+)/(?P<user_id>\d+)/(?P<back>back_to_start|back_to_category)/$",
                    views.tool_report_problem,
                    name="kiosk_tool_report_problem",
                ),
                re_path(
                    r"^tool_post_comment/(?P<tool_id>\d+)/(?P<user_id>\d+)/(?P<back>back_to_start|back_to_category)/$",
                    views.tool_post_comment,
                    name="kiosk_tool_post_comment",
                ),
                # Keeping for backwards compatibility (bookmarked links with location)
                re_path(r"^(?P<location>.+)/$", views.kiosk, name="kiosk"),
                path("", views.kiosk, name="kiosk"),
            ]
        ),
    )
]
