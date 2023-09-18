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
            let inline_attributes = $('.inline-group');
            if(selector.val()) {
                /* hide everything but name and parent_tool */
                inline_attributes.hide();
                rows_except_name_and_parent.hide();
                rows_except_name_and_parent.parent().hide();
                $(".form-row.field-name,.form-row.field-parent_tool").parent().show();
            } else {
                inline_attributes.show();
                rows_except_name_and_parent.show();
                rows_except_name_and_parent.parent().show();
            }
        }
        selector.change(hide_fields);
        hide_fields()

        add_required_class();
    })(django.jQuery);
});