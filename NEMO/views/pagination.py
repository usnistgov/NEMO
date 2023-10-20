from django.core.paginator import Paginator
from django.db.models import QuerySet


class SortedPaginator(Paginator):
    def __init__(self, object_list, request, per_page=None, order_by=None, orphans=0, allow_empty_first_page=True):
        per_page = self.get_session_per_page(request, object_list, per_page)
        self.page_number = request.GET.get("p")
        self.order_by = request.GET.get("o", order_by)
        if object_list and isinstance(object_list, QuerySet) and self.order_by:
            object_list = object_list.order_by(self.order_by)
        if per_page == "0":
            self.object_list = object_list
            per_page = self.count
        super().__init__(object_list, per_page, orphans, allow_empty_first_page)

    def get_current_page(self):
        return super().get_page(self.page_number)

    def get_session_per_page(self, request, query_set, default_per_page: str = None):
        per_page_requested = request.GET.get("pp")
        if request and query_set and isinstance(query_set, QuerySet):
            try:
                name = query_set.model._meta.model_name
                per_page_name = f"{name}_per_page"
                if per_page_requested:
                    request.session[per_page_name] = per_page_requested
                if not default_per_page:
                    default_per_page = request.session[per_page_name]
            except KeyError:
                # No session per page variable set
                pass
        return per_page_requested or default_per_page or "25"
