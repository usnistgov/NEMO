window.addEventListener("load", function()
{
    (function ($)
    {
        function update_input_form()
        {
            $('.questions_preview input, .questions_preview textarea, .questions_preview select').each(function (index, element) {
                $(element).attr('form', 'questions_preview_form')
            })
        }
        function update_validation_button()
        {
            let valid_message = $("#form_validity")
            if (valid_message)
            {
                if(document.querySelector('#questions_preview_form').checkValidity())
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
        $('.questions_preview').on('change keyup', "input[required][form='questions_preview_form'], textarea[required][form='questions_preview_form'], select[required][form='questions_preview_form']", update_validation_button);
        $('body').on('question-group-changed', function()
        {
            update_input_form();
            update_validation_button();
        });
        update_input_form();
        update_validation_button();
    })(django.jQuery);
});