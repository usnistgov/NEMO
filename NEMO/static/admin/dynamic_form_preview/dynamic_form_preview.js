window.addEventListener("load", function()
{
    (function ($)
    {
        /* set a separate form for testing post_usage data */
        $('form').last().after('<form id="dynamic_form_preview_form"></form>');

        function update_input_form()
        {
            $('.dynamic_form_preview input, .dynamic_form_preview textarea, .dynamic_form_preview select').each(function (index, element) {
                $(element).attr('form', 'dynamic_form_preview_form')
            })
        }
        function update_validation_button()
        {
            let valid_message = $("#form_validity")
            if (valid_message)
            {
                if(document.querySelector('#dynamic_form_preview_form').checkValidity())
                {
                    valid_message.removeClass("invalid");
                    valid_message.text("The form is valid!");
                }
                else
                {
                    valid_message.addClass("invalid");
                    valid_message.text("The form is invalid");
                }
            }
        }
        $('.dynamic_form_preview').on('change keyup', "input[form='dynamic_form_preview_form'], textarea[form='dynamic_form_preview_form'], select[form='dynamic_form_preview_form']", update_validation_button);
        $('body').on('question-group-changed', function()
        {
            update_input_form();
            update_validation_button();
        });
        update_input_form();
        update_validation_button();
    })(django.jQuery);
});