window.addEventListener("load", function()
{
    (function ($)
    {
        let selector = $('#id_parent_tool');

        let required_fields = ['category:', 'location:', 'phone number:', 'primary owner:'];
        function add_required_class()
        {
            let required_label = $('label').filter(function(){ return required_fields.includes($(this).text().trim().toLowerCase());})
            required_label.addClass('required')
        }

        function hide_fields()
        {
            let rows_except_name_and_parent = $(".form-row:not(.field-name,.field-parent_tool)");
            if(selector.val()) {
                /* hide everything but name and parent_tool */
                rows_except_name_and_parent.hide();
                rows_except_name_and_parent.parent().hide();
                $(".form-row.field-name,.form-row.field-parent_tool").parent().show();
            } else {
                rows_except_name_and_parent.show();
                rows_except_name_and_parent.parent().show();
            }
        }
        selector.change(hide_fields);
        hide_fields()

        /* set a separate form for testing post_usage data */
        $('#tool_form').after('<form id="questions_preview_form"></form>')
        add_required_class();
    })(django.jQuery);
});