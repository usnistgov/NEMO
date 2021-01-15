from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render
from django.template import Template, Context
from django.views.decorators.http import require_http_methods

from NEMO import rates
from NEMO.forms import ConsumableWithdrawForm
from NEMO.models import Consumable, User, ConsumableWithdraw, Project
from NEMO.utilities import send_mail, EmailCategory
from NEMO.views.customization import get_media_file_contents, get_customization


@staff_member_required(login_url=None)
@require_http_methods(['GET', 'POST'])
def consumables(request):
	form = ConsumableWithdrawForm(request.POST or None, initial={'quantity': 1})
	rate_dict = rates.rate_class.get_consumable_rates(Consumable.objects.all())

	dictionary = {
		'users': User.objects.filter(is_active=True),
		'consumables': Consumable.objects.filter(visible=True).order_by('category', 'name'),
		'rates': rate_dict,
	}

	if form.is_valid():
		withdraw = form.save(commit=False)
		make_withdrawal(consumable=withdraw.consumable, merchant=request.user, customer=withdraw.customer, quantity=withdraw.quantity, project=withdraw.project)
		form = ConsumableWithdrawForm(initial={'quantity': 1})
		messages.success(request, f'The withdrawal of {withdraw.quantity} of {withdraw.consumable} for {withdraw.customer} was successfully logged and will be billed to project {withdraw.project}.', extra_tags="data-speed=9000")
	else:
		if hasattr(form, 'cleaned_data') and 'customer' in form.cleaned_data:
			dictionary['projects'] = form.cleaned_data['customer'].active_projects()

	dictionary['form'] = form
	return render(request, 'consumables.html', dictionary)


def make_withdrawal(consumable: Consumable, quantity: int, project: Project, merchant:User, customer:User):
	withdraw = ConsumableWithdraw.objects.create(consumable=consumable, quantity=quantity, merchant=merchant, customer=customer, project=project)
	withdraw.consumable.quantity -= withdraw.quantity
	withdraw.consumable.save()


def send_reorder_supply_reminder_email(consumable: Consumable):
	user_office_email = get_customization('user_office_email_address')
	message = get_media_file_contents('reorder_supplies_reminder_email.html')
	if user_office_email and message:
		subject = f"Time to order more {consumable.name}"
		rendered_message = Template(message).render(Context({'item': consumable}))
		send_mail(subject=subject, content=rendered_message, from_email=user_office_email, to=[consumable.reminder_email], email_category=EmailCategory.SYSTEM)