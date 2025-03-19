window.addEventListener("load", function()
{
    (function ($)
    {
        /* add the form id to all the inputs of the preview */
        function update_input_form(preview_id)
        {
            let form_id = $("#" + preview_id).data("form-id");
            $('#' + preview_id + ' input, #' + preview_id + ' textarea, #' + preview_id + ' select').each(function (index, element)
            {
                $(element).attr("form", form_id);
            })
        }

        /* update the button displaying whether the form is valid or not */
        function update_validation_button(preview_id)
        {
            let form_id = $("#" + preview_id).data("form-id");
            let valid_message = $("#" + preview_id + " .form_validity");
            if (valid_message)
            {
                if(document.querySelector('#' + form_id).checkValidity())
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

        /* apply for each preview */
        $(".dynamic_form_preview").each(function (index, element)
        {
            let form_id = "dynamic_form_preview_form_" + index;
            let preview_id = "dynamic_form_preview_" + index;
            /* set the new id, so we can make sure to update the right preview */
            $(element).attr("id", preview_id);
            /* also set the form id, so we can easily retrieve it later */
            $(element).data("form-id", form_id);

            /* create a separate form for testing dynamic form data */
            $("form").last().after('<form id="' + form_id + '"></form>');

            update_input_form(preview_id);
            update_validation_button(preview_id);
        });

        /* bind events to the correct preview */
        $("body").on("dynamic-form-group-changed dynamic-form-field-changed", function(event, data)
        {
            let preview_id = $('.dynamic_form[data-field-name="' + data.field_name + '"]').closest(".dynamic_form_preview").attr("id");
            update_input_form(preview_id);
            update_validation_button(preview_id);
        });
    })(django.jQuery);
});

function csrf_token()
{
    return document.getElementsByName("csrfmiddlewaretoken")[0].value;
}

function auto_size_textarea(textarea, rows)
{
	if (textarea)
	{
		textarea.rows = rows || 1;
		textarea.style.height = '';
		textarea.style.height = textarea.scrollHeight + 3 + 'px';
	}
}