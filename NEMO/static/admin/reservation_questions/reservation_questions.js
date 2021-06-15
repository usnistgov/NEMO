window.addEventListener("load", function()
{
    (function ($)
    {
        /* set a separate form for testing questions data */
        $('#reservationquestions_form').after('<form id="questions_preview_form"></form>')
    })(django.jQuery);
});