window.addEventListener("load", function() {
    (function ($) {
        let selector = $('#id_parent_tool');

        let required_fields = ['category:', 'location:', 'phone number:', 'primary owner:'];
        function add_required_class() {
            let required_label = $('label').filter(function(){ return required_fields.includes($(this).text().trim().toLowerCase());})
            required_label.addClass('required')
        }

        function hide_fields(){
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
        $('#tool_form').after('<form id="post_usage_preview_form"></form>')
        function update_input_form() {
            $('.post_usage_preview input, .post_usage_preview select').each(function (index, element) {
                $(element).attr('form', 'post_usage_preview_form')
            })
        }
        function update_validation_button() {
            let valid_message = $("#form_validity")
            if (valid_message) {
                if(document.querySelector('#post_usage_preview_form').checkValidity()) {
                    valid_message.removeClass("invalid");
                    valid_message.text("The form is valid!");
                }
                else {
                    valid_message.addClass("invalid");
                    valid_message.text("The form is invalid");
                }
            }
        }
        $('.post_usage_preview').on('change keyup', "input[required][form='post_usage_preview_form'], select[required][form='post_usage_preview_form']", update_validation_button);
        $('body').on('question-group-changed', function(){
            update_input_form();
            update_validation_button();
        });
        update_input_form();
        update_validation_button();
        add_required_class();
    })(django.jQuery);
});