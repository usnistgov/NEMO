from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from NEMO.constants import FEEDBACK_MAXIMUM_LENGTH
from NEMO.utilities import EmailCategory, parse_parameter_string, render_email_template, send_mail
from NEMO.views.customization import EmailsCustomization, get_media_file_contents, resolve_email_customization


@login_required
@require_http_methods(["GET", "POST"])
def feedback(request):
    recipient = EmailsCustomization.get("feedback_email_address")
    email_contents = get_media_file_contents("feedback_email.html")
    if not recipient or not email_contents:
        return render(request, "feedback.html", {"customization_required": True})

    if request.method == "GET":
        return render(request, "feedback.html")
    contents = parse_parameter_string(request.POST, "feedback", FEEDBACK_MAXIMUM_LENGTH)
    if contents == "":
        return render(request, "feedback.html")
    dictionary = {
        "contents": contents,
        "user": request.user,
        "default_subject": "Feedback from " + str(request.user),
        "default_from_email": request.user.email,
        "default_cc_emails": "",
    }

    email = render_email_template(email_contents, dictionary, request)
    subject, from_email, cc = resolve_email_customization("feedback_email", dictionary)
    send_mail(
        subject=subject,
        content=email,
        from_email=from_email,
        to=[recipient],
        cc=cc,
        email_category=EmailCategory.FEEDBACK,
    )
    dictionary = {
        "title": "Feedback",
        "heading": "Thanks for your feedback!",
        "content": "Your feedback has been sent to the staff. We will follow up with you as soon as we can.",
    }
    return render(request, "acknowledgement.html", dictionary)
