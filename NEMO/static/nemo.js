String.prototype.capitalize = function() {
    return this.charAt(0).toUpperCase() + this.slice(1);
}

// This function allows making regular interval calls to a function only when the tab/window is visible.
// It also gets called when the tab/window becomes visible (changing tabs, minimizing window etc.)
// This function is safe in the sense that is can be called multiple times with the same function.
// It will clear any previously set events and replace them with the new ones.
let function_handlers = {};
function set_interval_when_visible(doc, function_to_repeat, time)
{
	const function_name = function_to_repeat.name;
	if (!function_name)
	{
		console.error("You can only call 'set_interval_when_visible' with a named function");
	}
	let call_function_when_visible = function () {
		if (!doc.hidden) function_to_repeat();
	}
	if (function_handlers[function_name])
	{
		// Clear the previous event and interval handler
		doc.removeEventListener("visibilitychange", function_handlers[function_name][0]);
		clearInterval(function_handlers[function_name][1]);
	}
	if (time)
	{
		doc.addEventListener("visibilitychange", call_function_when_visible);
		let intervalHandle = setInterval(call_function_when_visible, time);
		if (function_name)
		{
			// Save new event and handler
			function_handlers[function_name] = [call_function_when_visible, intervalHandle];
		}
	}
}

// This function allows any page to switch between content tabs in
// the Bootstrap framework. It is generally called upon loading the page.
function switch_tab(element)
{
	element.preventDefault();
	$(this).tab('show')
}

function set_item_link_callback(callback)
{
	$("a[data-item-type='tool'], a[data-item-type='area']").each(function()
	{
		$(this).click({"callback": callback}, callback);
	});
}

// This function allows categories in the tool tree sidebar to be expanded and collapsed.
// It must be called upon loading any page that uses the tool tree.
function enable_item_tree_toggling()
{
	$('label.tree-toggler').click(toggle_branch);
}

// This function toggles a tool category branch for the sidebar in the calendar & tool control pages.
function toggle_branch()
{
	$(this).parent().children('ul.tree').toggle(300, save_sidebar_state);
}

function on_item_search_selection(jquery_event, search_selection, dataset_name)
{
	$('#item_search').typeahead('val', '');
	expand_to_item(search_selection.id, search_selection.type);
}

// This function toggles all parent categories of a tool/area and selects the tool.
function expand_to_item(id, type)
{
	$("#sidebar a").removeClass('selected');
	$("#"+type+"-"+id).addClass('selected').click().parents('ul.tree').show();
	save_sidebar_state();
}

// This function expands all tool category branches for the sidebar in the calendar & tool control pages.
function expand_all_categories()
{
	$(".item_tree ul.tree.area-list").show();
	$(".item_tree ul.tree.tool-list").show();
	$("#search").focus();
	save_sidebar_state();
}

// This function collapses all tool category branches for the sidebar in the calendar & tool control pages.
function collapse_all_categories()
{
	$(".item_tree ul.tree.tool-list").hide();
	$(".item_tree ul.tree.area-list").hide();
	$("#search").focus();
	save_sidebar_state();
}

function get_qualified_tools_for_user(user_id) {
	ajax_get("/api/users/"+user_id+"/", {}, (data) => {
		localStorage.setItem("qualifiedTools", data.qualifications)
	})
}

function toggle_qualified_tools() {
	// Toggle local storage data value
	if (localStorage.getItem("showQualifiedTools") === "true") {
		localStorage.setItem("showQualifiedTools", "false");
	} else {  // Item showQualifiedTools is 'false' or not set.
		localStorage.setItem("showQualifiedTools", "true");
	}

	set_qualified_tools_button_status(
		localStorage.getItem("showQualifiedTools") === "true"
	)

	update_tool_list_display("toggle");
	if (localStorage.getItem("showQualifiedTools") === "true") {
		hide_empty_tool_categories();
	} else {
		show_all_tool_categories();
	}
}

function update_tool_list_display(item_function) {
	// Retrieve the list of tools the user is qualified for.
	let availableToolList = localStorage.getItem("qualifiedTools").split(",");

	// Go through the list of tools in the sidebar and toggle the ones that the user is
	// not qualified for.
	$("a[data-item-type='tool']").each((index, item) => {
		let $item = $(item);
		if($.inArray($item.attr("data-item-id"), availableToolList) === -1) {
			$item[item_function]();
		}
	})
}

function hide_empty_tool_categories() {
	$("li.tool-category").each((catIdx, category) => {
		let categoryHasItem = false;
		$(category).find("li>a").each((toolIdx, tool) => {
			let toolStyle = $(tool).attr("style");

			if(toolStyle===undefined || toolStyle!=="display: none;") {
				categoryHasItem = true;
				return;
			}
		})

		if (!categoryHasItem) {
			$(category).hide();
		}
	})
}

function show_all_tool_categories() {
	$("li.tool-category").each((catIdx, category) => {
		$(category).show();
	})
}

function set_qualified_tools_button_status(btn_active) {
	if (btn_active) {
		$("#qualified_tools_btn").addClass("active")
	} else {
		$("#qualified_tools_btn").removeClass("active")
	}
}

function toggle_item_categories(item_type)
{
	let one_visible = $(".item_tree ul.tree."+item_type+"-list li:visible").length >0;
	if (one_visible)
	{
		$(".item_tree ul.tree."+item_type+"-list").hide();
	}
	else
	{
		$(".item_tree ul.tree."+item_type+"-list").show();
	}
	$("#search").focus();
	save_sidebar_state();
}

function get_selected_item() {
	let selected_item = $(".selected");
	// Exactly one thing should be selected at a time, otherwise there's an error.
	if (!(selected_item && selected_item.length === 1))
	{
	return undefined;
	}
	let jq_selected_item = $(selected_item[0])
	// Check if the selected item is a special link. Otherwise, get its item ID.
	if(jq_selected_item.hasClass('personal_schedule'))
	{
		return 'personal_schedule';
	}

	if(jq_selected_item.hasClass('all_tools'))
	{
		return 'all_tools';
	}
	if(jq_selected_item.hasClass('all_areas'))
	{
		return 'all_areas';
	}
	if(jq_selected_item.hasClass('all_areastools'))
	{
		return 'all_areastools';
	}

	return JSON.stringify({'id': jq_selected_item.data('item-id'), 'type': jq_selected_item.data('item-type'), 'element_name': jq_selected_item.data('item-name')});
}

// This function visually highlights a clicked link with a gray background.
function set_selected_item(element)
{
	$("#sidebar a").removeClass('selected');
	$(element).addClass('selected');
	save_sidebar_state();
}

function set_selected_item_by_id(item_id, item_type)
{
	let item = $("#" + item_type + "-" + item_id);
	if(item.length === 1)
	{
		$("#sidebar a").removeClass('selected');
		item.addClass('selected');
	}
}

function set_selected_item_by_class(item_class)
{
	let item = $("."+item_class);
	if(item.length === 1)
	{
		$("#sidebar a").removeClass('selected');
		item.addClass('selected');
	}
}

function save_sidebar_state()
{
	let showQualifiedTools = localStorage.getItem("showQualifiedTools");
	let qualifiedTools = localStorage.getItem("qualifiedTools");

	localStorage.clear();
	let categories = $(".item_tree ul.tree");
	for(let c = 0; c < categories.length; c++)
	{
		let category = categories[c].getAttribute('data-category');
		localStorage[category] = $(categories[c]).is(':visible');
	}
	let selected_item = get_selected_item();
	if (selected_item)
	{
		localStorage['Selected item ID'] = selected_item;
	}

	if(showQualifiedTools !== null) {
		localStorage.setItem("showQualifiedTools", showQualifiedTools)
	}
	localStorage.setItem("qualifiedTools", qualifiedTools)
}

function load_sidebar_state()
{
	let categories = $(".item_tree ul.tree");
	for(let c = 0; c < categories.length; c++)
	{
		let category = categories[c];
		let name = category.getAttribute('data-category');
		let state = localStorage[name];
		if(state === "true")
		{
			$(category).show();
		}
		else
		{
			$(category).hide();
		}
	}
	let selected = localStorage['Selected item ID'];
	if (selected === 'personal_schedule' || selected === 'all_tools' || selected === 'all_areas' || selected === 'all_areastools' )
	{
		set_selected_item_by_class(selected);
	} else if (selected)
	{
		let selected_item = JSON.parse(selected)
		set_selected_item_by_id(selected_item.id, selected_item.type);
	}
}

function load_qualified_tools() {
	// Set available tool button status
	let qualifiedToolButtonState = localStorage.getItem("showQualifiedTools") === "true";
	set_qualified_tools_button_status(qualifiedToolButtonState);

	// Display the list of tools according to the 'showAvailableTools' value
	update_tool_list_display(qualifiedToolButtonState?"hide":"show");
	if (qualifiedToolButtonState) {
		hide_empty_tool_categories();
	} else {
		show_all_tool_categories();
	}
}


// Use this function to display a Bootstrap modal when an AJAX call is successful and contains content to render.
// Use this function with ajax_get(), ajax_post() or other similar functions.
function ajax_success_callback(response, status, xml_http_request)
{
	if(response)
	{
		$("#dialog .modal-content").html(response);
		$("#dialog").modal('show');
	}
}

// This function returns a callback. Upon AJAX message failure, the
// callback displays the error message in a Bootstrap modal dialog.
// Use this function with ajax_get(), ajax_post() or other similar functions.
function ajax_failure_callback(title, preface)
{
	preface = preface || "";
	function callback(xml_http_request, status, exception)
	{
		let dialog_contents =
			"<div class='modal-header'>" +
			"<button type='button' class='close' data-dismiss='modal'>&times;</button>" +
			"<h4 class='modal-title'>" + title + "</h4>" +
			"</div>" +
			"<div class='modal-body'>" +
			[preface, xml_http_request.responseText].join(" ") +
			"</div>";
		$("#dialog .modal-content").html(dialog_contents);
		$("#dialog").modal('show');
	}

	return callback;
}

function ajax_complete_callback(title, preface)
{
	preface = preface || "";
	function callback(response, status, xml_header_request)
	{
		if (status !== "error")
		{
			return;
		}
		let dialog_contents =
			"<div class='modal-header'>" +
			"<button type='button' class='close' data-dismiss='modal'>&times;</button>" +
			"<h4 class='modal-title'>" + title + "</h4>" +
			"</div>" +
			"<div class='modal-body'>" +
			[preface, xml_header_request.responseText].join(" ") +
			"</div>";
		$("#dialog .modal-content").html(dialog_contents);
		$("#dialog").modal('show');
	}

	return callback;
}

// Take all the elements in a form and put them in a JavaScript object.
function serialize(form_selector, ajax_message)
{
	if (ajax_message === undefined)
	{
		ajax_message = {};
	}
	let form_values = $(form_selector).serializeArray();
	for(let c = 0; c < form_values.length; c++)
		ajax_message[form_values[c].name] = form_values[c].value;
	return ajax_message;
}

function ajax_get(url, contents, success_callback, failure_callback, always_callback, traditional_serialization)
{
	ajax_message(url, "GET", contents, success_callback, failure_callback, always_callback, traditional_serialization)
}

function ajax_post(url, contents, success_callback, failure_callback, always_callback, traditional_serialization)
{
	if(contents === undefined)
	{
		contents = {};
	}
	//noinspection JSUnresolvedFunction
	contents.csrfmiddlewaretoken = csrf_token();
	ajax_message(url, "POST", contents, success_callback, failure_callback, always_callback, traditional_serialization)
}

function ajax_message(url, type, contents, success_callback, failure_callback, always_callback, traditional_serialization)
{
	let options =
	{
		"data": contents,
		"type": type,
		"traditional": traditional_serialization === true
	};
	let message = jQuery.ajax(url, options);
	if(success_callback !== undefined)
	{
		message.done(success_callback);
	}
	if(failure_callback !== undefined)
	{
		message.fail(failure_callback);
	}
	if(always_callback !== undefined)
	{
		message.always(always_callback);
	}
}

//noinspection JSUnusedGlobalSymbols
function on_change_configuration(url, configuration_id, slot, choice)
{
	let reconfiguration_properties =
	{
		"configuration_id": configuration_id,
		"slot": slot,
		"choice": choice
	};
	let failure_dialog = ajax_failure_callback("Configuration change failed", "There was a problem while changing this tool's configuration.");
	ajax_post(url, reconfiguration_properties, undefined, failure_dialog);
}

function autofocus(selector)
{
	$("#dialog").one('shown.bs.modal', function()
	{
		$(selector).focus();
	});
}

function toggle_details(element)
{
	$(element).children('.chevron').toggleClass('glyphicon-chevron-right glyphicon-chevron-down', 200);
	return false;
}

function add_to_list(list_selector, on_click, id, text, removal_title, input_name)
{
	let div_id = input_name + "_" + id;
	let div_id_selector = "#" + div_id;
	let addition =
		'<div id="' + div_id + '">' +
		'<a href="javascript:' + on_click + '(' + id + ')" class="grey hover-black" title="' + removal_title + '">' +
		'<span class="glyphicon glyphicon-remove-circle"></span>' +
		'</a> ' + text +
		'<input type="hidden" name="' + input_name + '" value="' + id + '"><br>' +
		'</div>';
	if($(list_selector).find('input').length === 0) // If the list is empty then replace the empty message with the list item.
	{
		$(list_selector).html(addition);
	}
	else if($(div_id_selector).length === 0) // Only add the element if it's not already in the list.
	{
		$(list_selector).append(addition);
	}
}

function remove_from_list(list_selector, div_id_selector, emptyMessage)
{
	$(list_selector + " > " + div_id_selector).remove();
	if($(list_selector).find('input').length === 0) // If the list is empty then replace it with the empty message.
	{
		$(list_selector).html(emptyMessage);
	}
}

// From http://twitter.github.io/typeahead.js/examples/
function matcher(items, search_fields)
{
	return function find_matches(query, callback)
	{
		// An array that will be populated with substring matches
		let matches = [];

		// Regular expression used to determine if a string contains the substring `query`
		let matching_regular_expression = new RegExp(query, 'i');

		// Iterate through the pool of strings and for any string that
		// contains the substring `query`, add it to the `matches` array
		$.each(items, function(item_index, item)
		{
			$.each(search_fields, function(search_field_index, search_term)
			{
				if(search_term in item && matching_regular_expression.test(item[search_term]))
				{
					// The typeahead jQuery plugin expects suggestions to a
					// JavaScript object, refer to typeahead docs for more info
					if (matches.indexOf(item) === -1)
					{
						// Only add if it's not already in the list
						matches.push(item);
					}
				}
			});
		});

		callback(matches);
	};
}

// This jQuery plugin integrates Twitter Typeahead directly with default parameters & search function.
//
// Example usage:
// function on_select(jquery_event, search_selection, dataset_name)
// {
//     ... called when an item is selected ...
// }
// $('#search').autocomplete('fruits', on_select, [{name:'apple', id:1}, {name:'banana', id:2}, {name:'cherry', id:3}]);
(function($)
{
	$.fn.autocomplete = function(dataset_name, select_callback, items_to_search, hide_type)
	{
		hide_type = hide_type || false;
		let search_fields = ['name', 'application_identifier'];
		let datasets =
		{
				source: matcher(items_to_search, search_fields),
				name: dataset_name,
				displayKey: 'name'
		};
		datasets['templates'] =
		{
			'suggestion': function(data)
			{
				let result = data['name'];
				if(!hide_type && data['type'])
				{
					result += '<br><span style="font-size:small; font-weight:bold; color:#bbbbbb">' + data['type'].capitalize() + '</span>';
				}
				if(data['application_identifier'])
				{
					result += '<span style="font-size:small; font-weight:bold; color:#bbbbbb" class="pull-right">' + data['application_identifier'] + '</span>';
				}
				return result;
			}
		};
		this.typeahead(
			{
				minLength: 1,
				hint: false,
				highlight: false
			},
			datasets
		);
		this.bind('typeahead:selected', select_callback);
		return this;
	};
}(jQuery));

// HTTP error 403 (unauthorized) is returned when the user's session
// has timed out and the web page makes an AJAX request. This 403 response
// is generated by the custom Django middleware called SessionTimeout.
// This function is registered as a global callback for AJAX completions
// in /templates/base.html so that when error 403 is returned the browser
// is redirected to the logout page, and then further redirected to the login
// page. This design is useful because some of NEMO's pages (such as the
// Calendar, Tool Control, and Status Dashboard) make regular polling AJAX requests.
function navigate_to_login_on_session_expiration(logout_url, event, xhr, status, error)
{
	if(xhr.status === 403)
	{
		window.location.href = logout_url;
	}
}

// This function as its name indicate will submit a form and disable the button
// Use it on an input submit onclick attribute: onclick="submit_and_disable(this)"
// Note: Depending on how validation is handled, this might not work if the form is invalid
function submit_and_disable(input_submit)
{
	if (input_submit.form.checkValidity())
	{
		// Add input name & value since js submit skips it
		if (input_submit.name)
		{
			$(input_submit.form).append($('<input>', {
				type: 'hidden',
				name: input_submit.name,
				value: input_submit.value
			}));
		}
		input_submit.form.submit();
		input_submit.disabled = true;
	}
}

function auto_size_textarea(textarea)
{
	textarea.rows = 1;
	textarea.style.height = '';
	textarea.style.height = textarea.scrollHeight + 3 + 'px';
}

function set_start_end_datetime_pickers(start_jq, end_jq, properties, end_before_start)
{
	start_jq.datetimepicker(properties);
	end_jq.datetimepicker(properties);
	if (end_before_start == null || end_before_start)
	{
		let end_date_picker = end_jq.data("DateTimePicker");
		start_jq.on("dp.change", function (e) { end_date_picker.minDate(e.date); });
	}
}
