from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from NEMO import rates
from NEMO.forms import ConsumableWithdrawForm
from NEMO.models import Consumable, User, ConsumableWithdraw, Project


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
		messages.success(request, f'The withdrawal of {withdraw.quantity} of {withdraw.consumable} for {withdraw.customer} was successfully logged.')
	else:
		if hasattr(form, 'cleaned_data') and 'customer' in form.cleaned_data:
			dictionary['projects'] = form.cleaned_data['customer'].active_projects()

	dictionary['form'] = form
	return render(request, 'consumables.html', dictionary)


def make_withdrawal(consumable: Consumable, quantity: int, project: Project, merchant:User, customer:User):
	withdraw = ConsumableWithdraw.objects.create(consumable=consumable, quantity=quantity, merchant=merchant, customer=customer, project=project)
	withdraw.consumable.quantity -= withdraw.quantity
	withdraw.consumable.save()