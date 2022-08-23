from django.shortcuts import render
from django.views.decorators.http import require_GET

from NEMO.decorators import staff_member_required
from NEMO.models import Chemical, ChemicalHazard


@staff_member_required
@require_GET
def safety_data_sheets(request):
	chemicals = Chemical.objects.all()
	hazards = ChemicalHazard.objects.all()

	return render(request, "safety_data_sheets.html", {"chemicals": chemicals, "hazards": hazards})
