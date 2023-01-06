from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Case, When
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from NEMO.decorators import staff_member_required
from NEMO.forms import SafetyIssueCreationForm, SafetyIssueUpdateForm
from NEMO.models import Chemical, ChemicalHazard, SafetyCategory, SafetyIssue, SafetyItem
from NEMO.templatetags.custom_tags_and_filters import navigation_url
from NEMO.utilities import (
	BasicDisplayTable,
	EmailCategory,
	distinct_qs_value_list,
	export_format_datetime,
	get_full_url,
	render_email_template,
	send_mail,
)
from NEMO.views.customization import EmailsCustomization, SafetyCustomization, get_media_file_contents
from NEMO.views.notifications import create_safety_notification, delete_notification, get_notifications


@login_required
@require_GET
def safety(request):
	dictionary = safety_dictionary("")
	if not dictionary["show_safety"]:
		if not dictionary["show_safety_issues"]:
			if not dictionary["show_safety_data_sheets"]:
				return redirect("safety_issues")
			return redirect("safety_data_sheets")
		return redirect("safety_issues")
	return redirect("safety_categories")


@login_required
@require_GET
def safety_categories(request, category_id=None):
	dictionary = safety_dictionary("safety")
	try:
		SafetyCategory.objects.get(pk=category_id)
	except SafetyCategory.DoesNotExist:
		pass
	safety_items_qs = SafetyItem.objects.filter(category_id=category_id)
	if not category_id and not safety_items_qs.exists():
		first_category = SafetyCategory.objects.first()
		category_id = first_category.id if first_category else None
	dictionary.update(
		{
			"category_id": category_id,
			"safety_items": SafetyItem.objects.filter(category_id=category_id),
			"safety_categories": SafetyCategory.objects.filter(
				id__in=distinct_qs_value_list(SafetyItem.objects.all(), "category_id")
			),
			"safety_general": SafetyItem.objects.filter(category_id__isnull=True).exists(),
		}
	)
	return render(request, "safety/safety.html", dictionary)


@login_required
@require_http_methods(["GET", "POST"])
def safety_issues(request):
	dictionary = safety_dictionary("safety_issues")
	if request.method == "POST":
		form = SafetyIssueCreationForm(request.user, data=request.POST)
		if form.is_valid():
			issue = form.save()
			send_safety_email_notification(request, issue)
			create_safety_notification(issue)
			messages.success(request, "Your safety concern was sent to the staff and will be addressed promptly")
			return redirect("safety_issues")
	tickets = SafetyIssue.objects.filter(resolved=False).order_by("-creation_time")
	if not request.user.is_staff:
		tickets = tickets.filter(visible=True)
	dictionary["tickets"] = tickets
	dictionary["notifications"] = get_notifications(request.user, SafetyIssue)
	return render(request, "safety/safety_issues.html", dictionary)


def send_safety_email_notification(request, issue):
	recipient = EmailsCustomization.get("safety_email_address")
	message = get_media_file_contents("safety_issue_email.html")
	if recipient and message:
		subject = "Safety issue"
		dictionary = {"issue": issue, "issue_absolute_url": get_full_url(issue.get_absolute_url(), request)}
		rendered_message = render_email_template(message, dictionary, request)
		from_email = issue.reporter.email if issue.reporter else recipient
		send_mail(
			subject=subject,
			content=rendered_message,
			from_email=from_email,
			to=[recipient],
			email_category=EmailCategory.SAFETY,
		)


@login_required
@require_GET
def resolved_safety_issues(request):
	dictionary = safety_dictionary("safety_issues")
	tickets = SafetyIssue.objects.filter(resolved=True)
	if not request.user.is_staff:
		tickets = tickets.filter(visible=True)
	dictionary["tickets"] = tickets
	return render(request, "safety/safety_issues_resolved.html", dictionary)


@staff_member_required
@require_http_methods(["GET", "POST"])
def update_safety_issue(request, ticket_id):
	dictionary = safety_dictionary("safety_issues")
	if request.method == "POST":
		ticket = get_object_or_404(SafetyIssue, id=ticket_id)
		form = SafetyIssueUpdateForm(request.user, data=request.POST, instance=ticket)
		if form.is_valid():
			issue = form.save()
			if issue.resolved:
				delete_notification(SafetyIssue, issue.id)
			messages.success(request, "This safety issue was updated successfully")
			return redirect("safety_issues")
	dictionary["ticket"] = get_object_or_404(SafetyIssue, id=ticket_id)
	return render(request, "safety/safety_issues_update.html", dictionary)


@login_required
@require_GET
def safety_data_sheets(request):
	chemicals = Chemical.objects.all().prefetch_related("hazards").order_by()
	hazards = ChemicalHazard.objects.all()

	for hazard in hazards:
		chemicals = chemicals.annotate(
			**{f"hazard_{hazard.id}": Case(When(hazards__in=[hazard.id], then=True), default=False)}
		)

	order_by = request.GET.get("o", "name")
	reverse_order = order_by.startswith("-")
	order = order_by[1:] if reverse_order else order_by
	chemicals = list(set(chemicals))
	if order == "name":
		chemicals.sort(key=lambda x: x.name.lower(), reverse=reverse_order)
	elif order.startswith("hazard_"):
		hazard_id = int(order[7:])
		chemicals.sort(key=lambda x: x.name.lower())
		chemicals.sort(key=lambda x: hazard_id in [h.id for h in x.hazards.all()], reverse=not reverse_order)

	dictionary = safety_dictionary("safety_data_sheets")
	dictionary.update({"chemicals": chemicals, "hazards": hazards, "order_by": order_by})

	return render(request, "safety/safety_data_sheets.html", dictionary)


@staff_member_required
@require_GET
def export_safety_data_sheets(request):
	hazards = ChemicalHazard.objects.all()

	table = BasicDisplayTable()
	table.add_header(("name", "Name"))
	for hazard in hazards:
		table.add_header((f"hazard_{hazard.id}", hazard.name))
	table.add_header(("keywords", "Keywords"))

	for chemical in Chemical.objects.all():
		chemical: Chemical = chemical
		values = {f"hazard_{hazard.id}": "X" for hazard in hazards if hazard in chemical.hazards.all()}
		values["name"] = chemical.name
		values["keywords"] = chemical.keywords
		table.add_row(values)

	response = table.to_csv()
	filename = f"safety_data_sheets_{export_format_datetime()}.csv"
	response["Content-Disposition"] = f'attachment; filename="{filename}"'
	return response


def safety_dictionary(tab):
	sds_url_exist = navigation_url("safety_data_sheets", "")
	dictionary = dict(
		show_safety=SafetyCustomization.get_bool("safety_show_safety"),
		show_safety_issues=SafetyCustomization.get_bool("safety_show_safety_issues"),
		show_safety_data_sheets=SafetyCustomization.get_bool("safety_show_safety_data_sheets") and sds_url_exist,
	)
	dictionary["show_tabs"] = len([key for key, value in dictionary.items() if value])
	dictionary["tab"] = tab
	if tab == "safety_issues":
		dictionary["safety_introduction"] = get_media_file_contents("safety_introduction.html")
	return dictionary
