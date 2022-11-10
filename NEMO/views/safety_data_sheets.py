from django.contrib.auth.decorators import login_required
from django.db.models import Case, When
from django.shortcuts import render
from django.views.decorators.http import require_GET

from NEMO.models import Chemical, ChemicalHazard


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
	reverse = order_by.startswith("-")
	order = order_by[1:] if reverse else order_by
	chemicals = list(set(chemicals))
	if order == "name":
		chemicals.sort(key=lambda x: x.name.lower(), reverse=reverse)
	elif order.startswith("hazard_"):
		hazard_id = int(order[7:])
		chemicals.sort(key=lambda x: x.name.lower())
		chemicals.sort(key=lambda x: hazard_id in [h.id for h in x.hazards.all()], reverse=not reverse)

	dictionary = {"chemicals": chemicals, "hazards": hazards, "order_by": order_by}

	return render(request, "safety_data_sheets.html", dictionary)
