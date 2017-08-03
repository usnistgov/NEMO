function mobile_search(query_element, base_url)
{
	query_element = $(query_element);
	var results_target = $(query_element.data('search-results-target')).html('');
	var query = query_element.val();
	if(query.length < 2)
		return;
	var search_base = query_element.data('search-base');
	var result_count = 0;
	var matching_regular_expression = new RegExp(query, 'i');
	var results = '<ul class="list-group">';
	$.each(search_base, function(item_index, item)
	{
		if(matching_regular_expression.test(item.name))
		{
			results += '<a href="' + base_url + item.id + '/"><li class="list-group-item list-group-item-info">' + item.name + '</li></a>';
			result_count++;
		}
	});
	results += '</ul>';
	if(result_count > 0)
		results_target.html(results);
}