from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from NEMO.models import News
from NEMO.utilities import format_datetime
from NEMO.views.notifications import create_news_notification, delete_news_notification, get_notifications


@login_required
@require_GET
def view_recent_news(request):
	dictionary = {
		'news': News.objects.filter(archived=False).order_by('-pinned', '-last_updated'),
		'notifications': get_notifications(request.user, News),
	}
	return render(request, 'news/recent_news.html', dictionary)


@login_required
@require_GET
def view_archived_news(request, page=1):
	page = int(page)
	news = News.objects.filter(archived=True).order_by('-created')
	paginator = Paginator(news, 20)
	if page < 1 or page > paginator.num_pages:
		return redirect(reverse('view_archived_news'))
	news = paginator.page(page)
	dictionary = {
		'news': news,
		'previous_page_number': news.previous_page_number() if news.has_previous() else None,
		'next_page_number': news.next_page_number() if news.has_next() else None,
	}
	return render(request, 'news/archived_news.html', dictionary)


@staff_member_required(login_url=None)
@require_POST
def archive_story(request, story_id):
	try:
		story = News.objects.get(id=story_id)
		story.archived = True
		story.save()
		delete_news_notification(story)
	except News.DoesNotExist:
		pass
	return redirect(reverse('view_recent_news'))


@staff_member_required(login_url=None)
@require_GET
def new_news_form(request):
	return render(request, 'news/new_news_form.html')


@staff_member_required(login_url=None)
@require_GET
def news_update_form(request, story_id):
	dictionary = {}
	try:
		dictionary['story'] = News.objects.get(id=story_id)
	except News.DoesNotExist:
		return redirect(reverse('view_recent_news'))
	return render(request, 'news/news_update_form.html', dictionary)


@staff_member_required(login_url=None)
@require_POST
def publish(request, story_id=None):
	now = timezone.now()
	pinned: bool = request.POST.get("pinned") == "on"
	notify = True
	if story_id:
		try:
			story = News.objects.get(id=story_id)
			update = request.POST.get('update')
			if update:
				update = f'\n\nUpdated on {format_datetime(now)} by {request.user.get_full_name()}:\n' + request.POST['update'].strip()
				story.all_content += update
				story.last_updated = now
				story.last_update_content = update.strip()
				story.update_count += 1
			else:
				# don't notify if all that's changed is the pinned value
				notify = False
			story.pinned = pinned
		except News.DoesNotExist:
			return redirect(reverse('view_recent_news'))
	else:
		story = News()
		story.title = request.POST['title']
		content = f'Originally published on {format_datetime(now)} by {request.user.get_full_name()}:\n' + request.POST['content'].strip()
		story.original_content = content
		story.created = now
		story.all_content = content
		story.last_updated = now
		story.last_update_content = content
		story.pinned = pinned
		story.update_count = 0
	story.save()
	if notify:
		create_news_notification(story)
	return redirect(reverse('view_recent_news'))
