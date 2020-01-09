(function ($) {
    $(function () {
        var selector = $('#id_parent_tool');

        function hide_fields(){
            if(selector.val()) {
                /* hide everything but name and parent_tool */
                $(".form-row:not(.field-name,.field-parent_tool)").hide();
                $(".form-row:not(.field-name,.field-parent_tool)").parent().hide();
                $(".form-row.field-name,.form-row.field-parent_tool").parent().show();
            } else {
                $(".form-row:not(.field-name,.field-parent_tool)").show();
                $(".form-row:not(.field-name,.field-parent_tool)").parent().show();
            }
        }
        selector.change(hide_fields);
        hide_fields()
    });
})(django.jQuery);