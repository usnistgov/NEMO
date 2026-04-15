from django.db import migrations

PREVIOUS_REMOTE_WORK_CUSTOMIZATION_NAME = "remote_work_on_behalf_of_user"
NEW_TOOL_CONTROL_BEHALF_OF_USER_CUSTOMIZATION_NAME = "tool_control_use_for_other_enabled"
NEW_TOOL_CONTROL_BEHALF_OF_USER_REMOTE_CUSTOMIZATION_NAME = "tool_control_use_for_other_remote_enabled"


def simplify_tool_usage_options(apps, schema_editor):
    Customization = apps.get_model("NEMO", "Customization")
    # rename all label customizations for tool control
    Customization.objects.filter(name="tool_control_use_self").update(name="tool_control_use_self_label")
    Customization.objects.filter(name="tool_control_use_self_training").update(
        name="tool_control_use_self_training_label"
    )
    Customization.objects.filter(name="tool_control_use_for_other_training").update(
        name="tool_control_use_for_other_training_label"
    )
    Customization.objects.filter(name="tool_control_use_for_other").update(name="tool_control_use_for_other_label")
    Customization.objects.filter(name="tool_control_use_for_other_remote").update(
        name="tool_control_use_for_other_remote_label"
    )
    Customization.objects.filter(name="remote_work_start_area_access_automatically").update(
        name="tool_control_use_for_other_remote_area_access_automatically_enabled"
    )
    Customization.objects.filter(name="training_show_self_option_in_tool_control").update(
        name="tool_control_use_self_training_enabled"
    )
    Customization.objects.filter(name="training_show_behalf_option_in_tool_control").update(
        name="tool_control_use_for_other_training_enabled"
    )
    Customization.objects.filter(name="tool_control_configuration_setting_template").update(
        name="tool_configuration_setting_template"
    )

    customization = Customization.objects.filter(name=PREVIOUS_REMOTE_WORK_CUSTOMIZATION_NAME).first()
    if not customization:
        # didn't exist, so default is only remote is set (same as previous "always")
        Customization.objects.update_or_create(
            name=NEW_TOOL_CONTROL_BEHALF_OF_USER_REMOTE_CUSTOMIZATION_NAME, defaults={"value": "enabled"}
        )
    if customization:
        old_value = customization.value
        if old_value == "always":
            # it was always, which was the default, so we need to keep it to off for regular and enabled for remote
            Customization.objects.update_or_create(
                name=NEW_TOOL_CONTROL_BEHALF_OF_USER_REMOTE_CUSTOMIZATION_NAME, defaults={"value": "enabled"}
            )
        elif old_value == "never":
            # it was "never", we need to enable for regular and disabled for both remote options
            Customization.objects.update_or_create(
                name=NEW_TOOL_CONTROL_BEHALF_OF_USER_CUSTOMIZATION_NAME, defaults={"value": "enabled"}
            )
            Customization.objects.update_or_create(
                name=NEW_TOOL_CONTROL_BEHALF_OF_USER_REMOTE_CUSTOMIZATION_NAME, defaults={"value": "off"}
            )
            Customization.objects.update_or_create(
                name="tool_control_use_for_other_remote_staff_charge_enabled", defaults={"value": "off"}
            )
        else:
            # it was ask, so we need to enable both
            Customization.objects.update_or_create(
                name=NEW_TOOL_CONTROL_BEHALF_OF_USER_CUSTOMIZATION_NAME, defaults={"value": "enabled"}
            )
            Customization.objects.update_or_create(
                name=NEW_TOOL_CONTROL_BEHALF_OF_USER_REMOTE_CUSTOMIZATION_NAME, defaults={"value": "enabled"}
            )
        Customization.objects.filter(name=PREVIOUS_REMOTE_WORK_CUSTOMIZATION_NAME).delete()


def reverse_simplify_tool_usage(apps, schema_editor):
    Customization = apps.get_model("NEMO", "Customization")
    behalf = Customization.objects.filter(name=NEW_TOOL_CONTROL_BEHALF_OF_USER_CUSTOMIZATION_NAME).first()
    behalf_remote = Customization.objects.filter(name=NEW_TOOL_CONTROL_BEHALF_OF_USER_REMOTE_CUSTOMIZATION_NAME).first()
    value_to_set = "always"
    behalf_val = behalf and behalf.value == "enabled"
    behalf_remote_val = not behalf_remote or behalf_remote.value == "enabled"
    if behalf_val and behalf_remote_val:
        value_to_set = "ask"
    elif behalf_val:
        value_to_set = "never"
    Customization.objects.update_or_create(
        name=PREVIOUS_REMOTE_WORK_CUSTOMIZATION_NAME, defaults={"value": value_to_set}
    )
    Customization.objects.filter(name=NEW_TOOL_CONTROL_BEHALF_OF_USER_CUSTOMIZATION_NAME).delete()
    Customization.objects.filter(name=NEW_TOOL_CONTROL_BEHALF_OF_USER_REMOTE_CUSTOMIZATION_NAME).delete()
    Customization.objects.filter(name="tool_control_use_for_other_remote_staff_charge_enabled").delete()
    # rename all label customizations for tool control
    Customization.objects.filter(name="tool_control_use_self_label").update(name="tool_control_use_self")
    Customization.objects.filter(name="tool_control_use_self_training_label").update(
        name="tool_control_use_self_training"
    )
    Customization.objects.filter(name="tool_control_use_for_other_training_label").update(
        name="tool_control_use_for_other_training"
    )
    Customization.objects.filter(name="tool_control_use_for_other_label").update(name="tool_control_use_for_other")
    Customization.objects.filter(name="tool_control_use_for_other_remote_label").update(
        name="tool_control_use_for_other_remote"
    )

    Customization.objects.filter(name="tool_control_use_for_other_remote_area_access_automatically_enabled").update(
        name="remote_work_start_area_access_automatically"
    )
    Customization.objects.filter(name="tool_control_use_self_training_enabled").update(
        name="training_show_self_option_in_tool_control"
    )
    Customization.objects.filter(name="tool_control_use_for_other_training_enabled").update(
        name="training_show_behalf_option_in_tool_control"
    )
    Customization.objects.filter(name="tool_configuration_setting_template").update(
        name="tool_control_configuration_setting_template"
    )


class Migration(migrations.Migration):

    dependencies = [
        ("NEMO", "0145_version_7_4_0"),
    ]

    operations = [migrations.RunPython(simplify_tool_usage_options, reverse_simplify_tool_usage)]
