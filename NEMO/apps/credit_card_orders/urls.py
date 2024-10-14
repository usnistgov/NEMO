from django.urls import include, path

from NEMO.apps.credit_card_orders.views import credit_card_orders

urlpatterns = [
    path(
        "credit_card_orders/",
        include(
            [
                path("", credit_card_orders.credit_card_orders, name="credit_card_orders"),
                path("create/", credit_card_orders.create_credit_card_order, name="create_credit_card_order"),
                path(
                    "create/<int:pdf_template_id>/",
                    credit_card_orders.create_credit_card_order,
                    name="create_credit_card_order_with_template",
                ),
                path(
                    "<int:credit_card_order_id>/edit/",
                    credit_card_orders.create_credit_card_order,
                    name="edit_credit_card_order",
                ),
                path(
                    "<int:credit_card_order_id>/cancel/",
                    credit_card_orders.cancel_credit_card_order,
                    name="cancel_credit_card_order",
                ),
                path(
                    "<int:credit_card_order_id>/render_pdf/",
                    credit_card_orders.render_credit_card_order_pdf,
                    name="render_credit_card_order_pdf",
                ),
                path(
                    "<int:credit_card_order_id>/approval/",
                    credit_card_orders.create_credit_card_order,
                    name="approval_credit_card_order",
                ),
                path("templates/", credit_card_orders.credit_card_order_templates, name="credit_card_order_templates"),
                path(
                    "form_fields/<int:form_id>/<str:group_name>/",
                    credit_card_orders.form_fields_group,
                    name="credit_card_orders_form_fields_group",
                ),
            ]
        ),
    )
]
