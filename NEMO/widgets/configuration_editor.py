from django.forms import Widget
from django.template import Context, Template
from django.urls import reverse
from django.utils.html import escape
from django.utils.safestring import mark_safe


class ConfigurationEditor(Widget):
    def __init__(self, attrs=None):
        self.url = reverse("tool_configuration")
        super().__init__(attrs)

    def render(self, name, value, attrs=None, **kwargs):
        result = ""
        for config in value["configurations"]:
            current_settings = config.current_settings_as_list()
            render_as_form = value.get("render_as_form", None)
            if render_as_form is None:
                render_as_form = not config.tool.in_use() and config.user_is_maintainer(value["user"])
            if len(current_settings) == 1:
                result += self.__render_for_one(config, render_as_form)
            else:
                result += self.__render_for_multiple(config, render_as_form)
        return mark_safe(result)

    def __render_for_one(self, config, render_as_form=None):
        current_setting = config.current_settings_as_list()[0]
        result = "<p><label class='form-inline'>" + escape(config.name) + ": "
        if render_as_form:
            result += (
                "<select class='form-control' style='width:300px; max-width:100%' onchange=\"on_change_configuration('"
                + self.url
                + "', "
                + str(config.id)
                + ', 0, this.value)">'
            )
            for index, option in enumerate(config.available_settings_as_list()):
                result += "<option value=" + str(index)
                if option == current_setting:
                    result += " selected"
                result += ">" + escape(option) + "</option>"
            result += "</select>"
        else:
            result += self.display_setting(current_setting)
        result += "</label></p>"
        return result

    def __render_for_multiple(self, config, render_as_form=None):
        result = "<p>" + escape(config.name) + ":<ul>"
        for setting_index, current_setting in enumerate(config.current_settings_as_list()):
            result += "<li>"
            if render_as_form:
                result += (
                    "<label class='form-inline'>"
                    + escape(config.configurable_item_name)
                    + " #"
                    + str(setting_index + 1)
                    + ": "
                )
                result += (
                    "<select class='form-control' style='width:300px' onchange=\"on_change_configuration('"
                    + self.url
                    + "', "
                    + str(config.id)
                    + ", "
                    + str(setting_index)
                    + ', this.value)">'
                )
                for option_index, option in enumerate(config.available_settings_as_list()):
                    result += "<option value=" + str(option_index)
                    if option == current_setting:
                        result += " selected"
                    result += ">" + escape(option) + "</option>"
                result += "</select></label>"
            else:
                result += (
                    config.configurable_item_name
                    + " #"
                    + str(setting_index + 1)
                    + ": "
                    + self.display_setting(current_setting)
                )
        result += "</ul></p>"
        return result

    def display_setting(self, current_setting):
        from NEMO.views.customization import ToolCustomization

        template = ToolCustomization.get("tool_control_configuration_setting_template")
        contents = "{{ current_setting }}"
        try:
            contents = Template(template).render(Context({"current_setting": escape(current_setting)}))
        except:
            pass
        return contents
