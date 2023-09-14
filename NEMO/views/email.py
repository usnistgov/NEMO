import csv
from logging import getLogger
from smtplib import SMTPException
from typing import List, Optional

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.validators import validate_email
from django.db.models import Q
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_GET, require_POST

from NEMO.decorators import any_staff_required
from NEMO.forms import EmailBroadcastForm
from NEMO.models import Account, Area, Project, Reservation, Tool, User, UserType
from NEMO.typing import QuerySetType
from NEMO.utilities import (
	EmailCategory,
	create_email_attachment,
	export_format_datetime,
	render_email_template,
	send_mail,
)
from NEMO.views.customization import (
	ApplicationCustomization,
	ToolCustomization,
	get_media_file_contents,
)

logger = getLogger(__name__)


@login_required
@require_GET
def get_email_form(request):
	recipient = request.GET.get("recipient", "")
	try:
		validate_email(recipient)
	except:
		return HttpResponseBadRequest("Recipient not valid.")
	return render(request, "email/email_form.html", {"recipient": recipient})


@login_required
@require_GET
def get_email_form_for_user(request, user_id):
	recipient = get_object_or_404(User, id=user_id)
	return render(request, "email/email_form.html", {"name": recipient.get_full_name(), "recipient": recipient.email})


@login_required
@require_POST
def send_email(request):
	try:
		recipient = request.POST["recipient"]
		validate_email(recipient)
		recipient_list = [recipient]
	except:
		return HttpResponseBadRequest("The intended recipient was not a valid email address. The email was not sent.")
	sender = request.user.email
	subject = request.POST.get("subject")
	body = request.POST.get("body")
	if request.POST.get("copy_me"):
		recipient_list.append(sender)
	try:
		send_mail(
			subject=subject,
			content=body,
			from_email=sender,
			bcc=recipient_list,
			email_category=EmailCategory.DIRECT_CONTACT,
		)
	except SMTPException as error:
		site_title = ApplicationCustomization.get("site_title")
		error_message = (
				f"{site_title} was unable to send the email through the email server. The error message that was received is: "
				+ str(error)
		)
		logger.exception(error_message)
		dictionary = {
			"title": "Email not sent",
			"heading": "There was a problem sending your email",
			"content": error_message,
		}
		return render(request, "acknowledgement.html", dictionary)
	dictionary = {"title": "Email sent", "heading": "Your email was sent"}
	return render(request, "acknowledgement.html", dictionary)


@any_staff_required
@require_GET
def email_broadcast(request, audience=""):
	dictionary = {}
	if audience == "tool" or audience == "tool-reservation":
		dictionary["search_base"] = Tool.objects.filter(visible=True)
	elif audience == "area":
		dictionary["search_base"] = Area.objects.all()
	elif audience == "project":
		dictionary["search_base"] = Project.objects.filter(active=True, account__active=True)
	elif audience == "account":
		dictionary["search_base"] = Account.objects.filter(active=True)
	elif audience == "user":
		user_types = UserType.objects.all()
		dictionary["user_types"] = user_types
		if not user_types:
			return redirect(f"{reverse('compose_email')}?audience={audience}")
	dictionary["audience"] = audience
	return render(request, "email/email_broadcast.html", dictionary)


@login_required
@require_GET
def compose_email(request):
	try:
		audience = request.GET["audience"]
		selection = request.GET.getlist("selection")
		# Check if the user is allowed to broadcast email
		error = check_user_allowed(request.user, audience, selection)
		if error:
			return HttpResponseBadRequest(error)
		no_type = request.GET.get("no_type") == "on"
		users, topic = get_users_for_email(audience, selection, no_type)
	except:
		dictionary = {"error": "You specified an invalid audience parameter"}
		# Only render the email_broadcast page when user is staff member
		if request.user.is_any_part_of_staff:
			return render(request, "email/email_broadcast.html", dictionary)
		else:
			return HttpResponseBadRequest("You specified an invalid audience parameter")
	generic_email_sample = get_media_file_contents("generic_email.html")
	dictionary = {
		"audience": audience,
		"selection": selection,
		"no_type": no_type,
		"users": users,
		"topic": topic,
		"user_emails": ";".join([email for user in users for email in user.get_emails(user.get_preferences().email_send_broadcast_emails)]),
		"active_user_emails": ";".join([email for user in users for email in user.get_emails(user.get_preferences().email_send_broadcast_emails) if user.is_active]),
	}
	if generic_email_sample:
		generic_email_context = {
			"title": "TITLE",
			"greeting": "Greeting",
			"contents": "Contents",
			"template_color": "#5bc0de",
		}
		dictionary["generic_email_sample"] = render_email_template(generic_email_sample, generic_email_context, request)
	return render(request, "email/compose_email.html", dictionary)


@any_staff_required
@require_GET
def export_email_addresses(request):
	try:
		audience = request.GET["audience"]
		selection = request.GET.getlist("selection")
		no_type = request.GET.get("no_type") == "on"
		only_active_users = request.GET.get("active") == "on"
		users, topic = get_users_for_email(audience, selection, no_type)
		response = HttpResponse(content_type="text/csv")
		writer = csv.writer(response)
		writer.writerow(["First", "Last", "Username", "Email"])
		if only_active_users:
			users = [user for user in users if user.is_active]
		for user in users:
			user: User = user
			for email in user.get_emails(user.get_preferences().email_send_broadcast_emails):
				writer.writerow([user.first_name, user.last_name, user.username, email])
		response["Content-Disposition"] = f'attachment; filename="email_addresses_{export_format_datetime()}.csv"'
		return response
	except:
		dictionary = {"error": "You specified an invalid audience parameter"}
		return render(request, "email/email_broadcast.html", dictionary)


@login_required
@require_POST
def send_broadcast_email(request):
	content = get_media_file_contents("generic_email.html")
	if not content:
		return HttpResponseBadRequest(
			"Generic email template not defined. Visit the customization page to upload a template."
		)
	form = EmailBroadcastForm(request.POST)
	if not form.is_valid():
		return render(request, "email/compose_email.html", {"form": form})
	# Check if the user is allowed to broadcast email
	error = check_user_allowed(request.user, form.cleaned_data["audience"], form.cleaned_data["selection"])
	if error:
		return HttpResponseBadRequest(error)
	dictionary = {
		"title": form.cleaned_data["title"],
		"greeting": form.cleaned_data["greeting"],
		"contents": form.cleaned_data["contents"],
		"template_color": form.cleaned_data["color"],
	}
	content = render_email_template(content, dictionary, request)
	active_choice = form.cleaned_data["only_active_users"]
	try:
		audience = form.cleaned_data["audience"]
		selection = form.cleaned_data["selection"]
		no_type = form.cleaned_data["no_type"]
		users, topic = get_users_for_email(audience, selection, no_type)
		if active_choice:
			users = users.filter(is_active=True)
	except Exception as error:
		warning_message = "Your email was not sent. There was a problem finding the users to send the email to."
		dictionary = {"error": warning_message}
		logger.warning(
			warning_message
			+ " audience: {}, only_active: {}. The error message that was received is: {}".format(
				audience, active_choice, str(error)
			)
		)
		return render(request, "email/compose_email.html", dictionary)
	if not users:
		dictionary = {"error": "The audience you specified is empty. You must send the email to at least one person."}
		return render(request, "email/compose_email.html", dictionary)
	subject = form.cleaned_data["subject"]
	if topic:
		subject = f"[{topic}] " + subject
	users = [email for user in users for email in user.get_emails(user.get_preferences().email_send_broadcast_emails)]
	sender: User = request.user
	if form.cleaned_data["copy_me"]:
		users += sender.get_emails(sender.get_preferences().email_send_broadcast_emails)
	attachments = [create_email_attachment(attachment.file, attachment.name) for attachment in request.FILES.getlist('attachments', [])]
	try:
		send_mail(
			subject=subject,
			content=content,
			from_email=sender.email,
			bcc=set(users),
			attachments=attachments,
			email_category=EmailCategory.BROADCAST_EMAIL,
		)
	except SMTPException as error:
		site_title = ApplicationCustomization.get("site_title")
		error_message = (
				f"{site_title} was unable to send the email through the email server. The error message that was received is: "
				+ str(error)
		)
		logger.exception(error_message)
		messages.error(request, message=error_message)
		return redirect("email_broadcast")
	messages.success(request, message="Your email was sent successfully")
	return redirect("email_broadcast")


@login_required
@require_POST
def email_preview(request):
	generic_email_template = get_media_file_contents("generic_email.html")
	if generic_email_template:
		form = EmailBroadcastForm(request.POST)
		email_context = {
			"title": form.data["title"],
			"greeting": form.data["greeting"],
			"contents": form.data["contents"],
			"template_color": form.data["color"],
		}
		email_content = render_email_template(generic_email_template, email_context, request)
		return HttpResponse(mark_safe(email_content))
	return HttpResponse()


# Returns users and an optional topic to add to the email subject
def get_users_for_email(audience: str, selection: List, no_type: bool) -> (QuerySetType[User], str):
	users = User.objects.none()
	topic = None
	if audience == "tool":
		users = User.objects.filter(qualifications__id__in=selection).distinct()
		if len(selection) == 1:
			topic = Tool.objects.filter(pk=selection[0]).first().name
	elif audience == "tool-reservation":
		upcoming_reservations = Reservation.objects.filter(cancelled=False, missed=False, shortened=False, tool__in=selection, end__gte=timezone.now())
		users = User.objects.filter(reservation_user__in=upcoming_reservations).distinct()
		if len(selection) == 1:
			topic = Tool.objects.filter(pk=selection[0]).first().name
	elif audience == "area":
		areas: QuerySetType[Area] = Area.objects.filter(pk__in=selection)
		access_levels = [access_level for area in areas for access_level in area.get_physical_access_levels()]
		user_filter = Q(physical_access_levels__in=access_levels)
		# if one of the access levels allows staff, add all staff & user office
		if any([access_level.allow_staff_access for access_level in access_levels]):
			user_filter |= Q(is_staff=True)
			user_filter |= Q(is_user_office=True)
		users = User.objects.filter(user_filter).distinct()
		if len(selection) == 1:
			topic = areas.first().name
	elif audience == "project":
		users = User.objects.filter(projects__id__in=selection).distinct()
		if len(selection) == 1:
			topic = Project.objects.filter(pk=selection[0]).first().name
	elif audience == "account":
		users = User.objects.filter(projects__account__id__in=selection).distinct()
		if len(selection) == 1:
			topic = Account.objects.filter(pk=selection[0]).first().name
	elif audience == "user":
		users = User.objects.all().distinct()
		if selection:
			users = (
				users.filter(Q(type_id__in=selection) | Q(type_id__isnull=no_type))
				if no_type
				else users.filter(type_id__in=selection)
			)
		elif no_type:
			users = users.filter(type_id__isnull=True)
	return users, topic

def check_user_allowed(user: User, audience: str, selection: str) -> Optional[str]:
	if not user.is_any_part_of_staff:
		allow_broadcast_upcoming_reservation = ToolCustomization.get_bool("tool_control_broadcast_upcoming_reservation")
		if not allow_broadcast_upcoming_reservation or audience != "tool-reservation":
			return "You may not broadcast email to this audience"
		else:
			tool = Tool.objects.filter(id__in=selection).first()
			if not tool or user not in tool.user_set.all():
				return "You can only send a broadcast email to users of a tool you are qualified to use"