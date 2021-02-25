from django.core.paginator import Paginator
from django.db.models import QuerySet


class SortedPaginator(Paginator):
    def __init__(self, object_list, request, per_page="25", order_by=None, orphans=0, allow_empty_first_page=True):
        per_page = request.GET.get("pp", per_page)
        self.page_number = request.GET.get("p")
        self.order_by = request.GET.get("o", order_by)
        if object_list and isinstance(object_list, QuerySet) and self.order_by:
            object_list = object_list.order_by(self.order_by)
        super().__init__(object_list, per_page, orphans, allow_empty_first_page)

    def get_current_page(self):
        return super().get_page(self.page_number)
