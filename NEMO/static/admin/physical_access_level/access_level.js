window.addEventListener("load", function() {
    (function ($) {
        let selector = $('#id_schedule');

        function hide_time_fields(){
            if(selector.val() === "1") {
                /* 1 is for weekday schedule, show times */
                $(".field-weekdays_start_time").show();
                $(".field-weekdays_end_time").show();
            } else {
                $(".field-weekdays_start_time").hide();
                $(".field-weekdays_end_time").hide();
            }
        }
        selector.change(hide_time_fields);
        hide_time_fields()
    })(django.jQuery);
});