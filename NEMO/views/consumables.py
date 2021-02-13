from logging import getLogger
from typing import List

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render, redirect
from django.template import Template, Context
from django.views.decorators.http import require_http_methods, require_POST

from NEMO import rates
from NEMO.forms import ConsumableWithdrawForm
from NEMO.models import Consumable, User, ConsumableWithdraw
from NEMO.utilities import send_mail, EmailCategory
from NEMO.views.customization import get_media_file_contents, get_customization

consumables_logger = getLogger(__name__)


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
		add_withdraw_to_session(request, withdraw)
		dictionary['projects'] = form.cleaned_data['customer'].active_projects()
	else:
		if hasattr(form, 'cleaned_data') and 'customer' in form.cleaned_data:
			dictionary['projects'] = form.cleaned_data['customer'].active_projects()

	dictionary['form'] = form
	return render(request, 'consumables.html', dictionary)


def add_withdraw_to_session(request, withdrawal: ConsumableWithdraw):
	request.session.setdefault('withdrawals', [])
	withdrawals: List = request.session.get('withdrawals')
	if withdrawals is not None:
		withdrawal_dict = {
			'customer': str(withdrawal.customer),
			'customer_id': withdrawal.customer_id,
			'consumable': str(withdrawal.consumable),
			'consumable_id': withdrawal.consumable_id,
			'project': str(withdrawal.project),
			'project_id': withdrawal.project_id,
			'quantity': withdrawal.quantity
		}
		withdrawals.append(withdrawal_dict)
	request.session['withdrawals'] = withdrawals


@staff_member_required(login_url=None)
@require_POST
def remove_withdraw_at_index(request, index: str):
	try:
		index = int(index)
		withdrawals: List = request.session.get('withdrawals')
		if withdrawals:
			del withdrawals[index]
	except Exception as e:
		consumables_logger.exception(e)
	return redirect("consumables")


@staff_member_required(login_url=None)
@require_POST
def make_withdrawals(request):
	withdrawals: List = request.session.get('withdrawals')
	for withdraw in withdrawals:
		make_withdrawal(consumable_id=withdraw['consumable_id'], merchant=request.user, customer_id=withdraw['customer_id'], quantity=withdraw['quantity'], project_id=withdraw['project_id'])
		messages.success(request, f'The withdrawal of {withdraw["quantity"]} of {withdraw["consumable"]} for {withdraw["customer"]} was successfully logged and will be billed to project {withdraw["project"]}.', extra_tags="data-speed=9000")
	del request.session['withdrawals']
	return redirect('consumables')


def make_withdrawal(consumable_id: int, quantity: int, project_id: int, merchant: User, customer_id: int):
	withdraw = ConsumableWithdraw.objects.create(consumable_id=consumable_id, quantity=quantity, merchant=merchant, customer_id=customer_id, project_id=project_id)
	withdraw.consumable.quantity -= withdraw.quantity
	withdraw.consumable.save()


def send_reorder_supply_reminder_email(consumable: Consumable):
	user_office_email = get_customization('user_office_email_address')
	message = get_media_file_contents('reorder_supplies_reminder_email.html')
	if user_office_email and message:
		subject = f"Time to order more {consumable.name}"
		rendered_message = Template(message).render(Context({'item': consumable}))
		send_mail(subject=subject, content=rendered_message, from_email=user_office_email, to=[consumable.reminder_email], email_category=EmailCategory.SYSTEM)
