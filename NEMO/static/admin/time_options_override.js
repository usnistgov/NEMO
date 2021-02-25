/*global Calendar, findPosX, findPosY, getStyle, get_format, gettext, gettext_noop, interpolate, ngettext, quickElement*/
window.addEventListener('load', function () {
    django.jQuery('document').ready(function () {
        for (let num=0; num < DateTimeShortcuts.clockInputs.length ; num++) {
            let clock_box = document.getElementById(DateTimeShortcuts.clockDivName + num);
            let time_list = clock_box.getElementsByClassName('timelist')[0]
            let time_link = quickElement('a', quickElement('li', time_list), gettext("11:59 p.m."), 'href', '#');
            time_link.addEventListener('click', function (e) {
                e.preventDefault();
                DateTimeShortcuts.handleClockQuicklink(num, -2);
            });
        }
        DateTimeShortcuts.handleClockQuicklink = function (num, val) {
            let d;
            if (val === -1) {
                d = DateTimeShortcuts.now();
            } else if (val === -2) {
                d = new Date(1970, 1, 1, 23, 59, 0, 0);
            } else {
                d = new Date(1970, 1, 1, val, 0, 0, 0);
            }
            DateTimeShortcuts.clockInputs[num].value = d.strftime(get_format('TIME_INPUT_FORMATS')[0]);
            DateTimeShortcuts.clockInputs[num].focus();
            DateTimeShortcuts.dismissClock(num);
        }
    });
});