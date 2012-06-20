#-*- coding: utf-8 -*-

import re
import os
import json
import logging
import urllib
import django.utils.simplejson as simplejson

from calendar import timegm
from datetime import datetime, timedelta

from urlparse import urljoin
from django import forms
from django.http import HttpResponse, HttpResponseRedirect
from django.template import RequestContext, loader
from django.conf import settings
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger, InvalidPage
from django.contrib.auth.decorators import (login_required,
                                            permission_required,
                                            user_passes_test)
from lib.mockup import generate_thread_per_category, generate_top_author
from kittystore.kittysastore import KittySAStore

from thread import AddTagForm

logger = logging.getLogger(__name__)


# @TODO : Move this into settings.py
MONTH_PARTICIPANTS = 284
MONTH_DISCUSSIONS = 82

STORE = KittySAStore(settings.KITTYSTORE_URL)

class SearchForm(forms.Form):
    target =  forms.CharField(label='', help_text=None,
                widget=forms.Select(
                    choices=(('Subject', 'Subject'),
                            ('Content', 'Content'),
                            ('SubjectContent', 'Subject & Content'),
                            ('From', 'From'))
                    )
                )

    keyword = forms.CharField(max_length=100,label='', help_text=None,
                widget=forms.TextInput(
                    attrs={'placeholder': 'Search this list.'}
                    )
                )


class AddCategoryForm(forms.Form):
    category =  forms.CharField(label='', help_text=None,
                widget=forms.TextInput(
                    attrs={'placeholder': 'Add a category...'}
                    )
                )
    from_url = forms.CharField(widget=forms.HiddenInput, required=False)


def index(request):
    t = loader.get_template('index.html')
    search_form = SearchForm(auto_id=False)
    base_url = settings.MAILMAN_API_URL % {
        'username': settings.MAILMAN_USER, 'password': settings.MAILMAN_PASS}
    #data = json.load(urlgrabber.urlopen(urljoin(base_url, 'lists')))
    #list_data = sorted(data['entries'], key=lambda elem: (elem['mail_host'], elem['list_name']))
    list_data = ['devel@fp.o', 'packaging@fp.o', 'fr-users@fp.o']
    c = RequestContext(request, {
        'app_name': settings.APP_NAME,
        'lists': list_data,
        'search_form': search_form,
        })
    return HttpResponse(t.render(c))

def add_category(request, mlist_fqdn, email_id):
    """ Add a category to a given message. """
    t = loader.get_template('add_tag_form.html')
    if request.method == 'POST':
        form = AddCategoryForm(request.POST)
        if form.is_valid():
            print "THERE WE ARE"
            # TODO: Add the logic to add the category
            if form.data['from_url']:
                return HttpResponseRedirect(form.data['from_url'])
            else:
                return HttpResponseRedirect('/')
    else:
        form = AddCategoryForm()
    c = RequestContext(request, {
        'app_name': settings.APP_NAME,
        'list_address': mlist_fqdn,
        'email_id': email_id,
        'addtag_form': form,
        })
    return HttpResponse(t.render(c))

def api(request):
    t = loader.get_template('api.html')
    c = RequestContext(request, {
        'app_name': settings.APP_NAME,
        })
    return HttpResponse(t.render(c))


def archives(request, mlist_fqdn, year=None, month=None, day=None):
    # No year/month: past 32 days
    # year and month: find the 32 days for that month
    end_date = None
    if year or month or day:
        try:
            start_day = 1
            end_day = 1
            start_month = int(month)
            end_month = int(month) + 1
            start_year = int(year)
            end_year = int(year)
            if day:
                start_day = int(day)
                end_day = start_day + 1
                end_month = start_month
            if start_month == 12:
                end_month = 1
                end_year = start_year + 1

            begin_date = datetime(start_year, start_month, start_day)
            end_date = datetime(end_year, end_month, end_day)
            month_string = begin_date.strftime('%B %Y')
        except ValueError, err:
            print err
            logger.error('Wrong format given for the date')

    if not end_date:
        today = datetime.utcnow()
        begin_date = datetime(today.year, today.month, 1)
        end_date = datetime(today.year, today.month+1, 1)
        month_string = 'Past thirty days'
    list_name = mlist_fqdn.split('@')[0]

    search_form = SearchForm(auto_id=False)
    t = loader.get_template('month_view.html')
    threads = STORE.get_archives(list_name, start=begin_date,
        end=end_date)

    participants = set()
    cnt = 0
    for msg in threads:
        # Statistics on how many participants and threads this month
        participants.add(msg.sender)
        msg.participants = STORE.get_thread_participants(list_name,
            msg.thread_id)
        msg.answers = STORE.get_thread_length(list_name,
            msg.thread_id)
        threads[cnt] = msg
        cnt = cnt + 1

    archives_length = STORE.get_archives_length(list_name)

    c = RequestContext(request, {
        'app_name': settings.APP_NAME,
        'list_name' : list_name,
        'list_address': mlist_fqdn,
        'search_form': search_form,
        'month': month_string,
        'month_participants': len(participants),
        'month_discussions': len(threads),
        'threads': threads,
        'archives_length': archives_length,
    })
    return HttpResponse(t.render(c))

def list(request, mlist_fqdn=None):
    if not mlist_fqdn:
        return HttpResponseRedirect('/')
    t = loader.get_template('recent_activities.html')
    search_form = SearchForm(auto_id=False)
    list_name = mlist_fqdn.split('@')[0]

    # Get stats for last 30 days
    today = datetime.utcnow()
    end_date = datetime(today.year, today.month, today.day)
    begin_date = end_date - timedelta(days=32)

    threads = STORE.get_archives(list_name=list_name,start=begin_date,
        end=end_date)

    participants = set()
    dates = {}
    cnt = 0
    for msg in threads:
        month = msg.date.month
        if month < 10:
            month = '0%s' % month
        day = msg.date.day
        if day < 10:
            day = '0%s' % day    
        key = '%s%s%s' % (msg.date.year, month, day)
        if key in dates:
            dates[key] = dates[key] + 1
        else:
            dates[key] = 1
        # Statistics on how many participants and threads this month
        participants.add(msg.sender)
        msg.participants = STORE.get_thread_participants(list_name,
            msg.thread_id)
        msg.answers = STORE.get_thread_length(list_name,
            msg.thread_id)
        threads[cnt] = msg
        cnt = cnt + 1

    # top threads are the one with the most answers
    top_threads = sorted(threads, key=lambda entry: entry.answers, reverse=True)

    # active threads are the ones that have the most recent posting
    active_threads = sorted(threads, key=lambda entry: entry.date, reverse=True)

    archives_length = STORE.get_archives_length(list_name)

    # top authors are the ones that have the most kudos.  How do we determine
    # that?  Most likes for their post?
    authors = generate_top_author()
    authors = sorted(authors, key=lambda author: author.kudos)
    authors.reverse()

    # Get the list activity per day
    days = dates.keys()
    days.sort()
    dates_string = ["%s/%s/%s" % (key[0:4], key[4:6], key[6:8]) for key in days]
    #print days
    #print dates_string
    evolution = [dates[key] for key in days]
    if not evolution:
        evolution.append(0)

    # threads per category is the top thread titles in each category
    threads_per_category = generate_thread_per_category()
    c = RequestContext(request, {
        'app_name': settings.APP_NAME,
        'list_name' : list_name,
        'list_address': mlist_fqdn,
        'search_form': search_form,
        'month': 'Recent activity',
        'month_participants': len(participants),
        'month_discussions': len(threads),
        'top_threads': top_threads[:5],
        'most_active_threads': active_threads[:5],
        'top_author': authors,
        'threads_per_category': threads_per_category,
        'archives_length': archives_length,
        'evolution': evolution,
        'dates_string': dates_string,
    })
    return HttpResponse(t.render(c))

def message (request, mlist_fqdn, messageid):
    ''' Displays a single message identified by its messageid '''
    list_name = mlist_fqdn.split('@')[0]

    search_form = SearchForm(auto_id=False)
    t = loader.get_template('message.html')
    message = STORE.get_email(list_name, messageid)
    message.email = message.email.strip()
    c = RequestContext(request, {
        'app_name': settings.APP_NAME,
        'list_name' : list_name,
        'list_address': mlist_fqdn,
        'message': message,
	'messageid' : messageid,
    })
    return HttpResponse(t.render(c))

def _search_results_page(request, mlist_fqdn, threads, search_type,
    page=1, num_threads=25, limit=None):
    search_form = SearchForm(auto_id=False)
    t = loader.get_template('search.html')
    list_name = mlist_fqdn.split('@')[0]
    res_num = len(threads)

    participants = set()
    for msg in threads:
        participants.add(msg.sender)

    paginator = Paginator(threads, num_threads)

    #If page request is out of range, deliver last page of results.
    try:
        threads = paginator.page(page)
    except (EmptyPage, InvalidPage):
        threads = paginator.page(paginator.num_pages)

    cnt = 0
    for msg in threads.object_list:
        msg.email = msg.email.strip()
        # Statistics on how many participants and threads this month
        participants.add(msg.sender)
        if msg.thread_id:
            msg.participants = STORE.get_thread_participants(list_name,
                msg.thread_id)
            msg.answers = STORE.get_thread_length(list_name,
                msg.thread_id)
        else:
            msg.participants = 0
            msg.answers = 0
        threads.object_list[cnt] = msg
        cnt = cnt + 1

    c = RequestContext(request, {
        'app_name': settings.APP_NAME,
        'list_name' : list_name,
        'list_address': mlist_fqdn,
        'search_form': search_form,
        'month': search_type,
        'month_participants': len(participants),
        'month_discussions': res_num,
        'threads': threads,
        'full_path': request.get_full_path(),
    })
    return HttpResponse(t.render(c))


def search(request, mlist_fqdn):
    keyword = request.GET.get('keyword')
    target = request.GET.get('target')
    page = request.GET.get('page')
    if keyword and target:
        url = '/search/%s/%s/%s/' % (mlist_fqdn, target, keyword)
        if page:
            url += '%s/' % page
    else:
        url = '/search/%s' % (mlist_fqdn)
    return HttpResponseRedirect(url)


def search_keyword(request, mlist_fqdn, target, keyword, page=1):
    ## Should we remove the code below? 
    ## If urls.py does it job we should never need it
    if not keyword:
        keyword = request.GET.get('keyword')
    if not target:
        target = request.GET.get('target')
    if not target:
        target = 'Subject'
    regex = '%%%s%%' % keyword
    list_name = mlist_fqdn.split('@')[0]
    if target.lower() == 'subjectcontent':
        threads = STORE.search_content_subject(list_name, keyword)
    elif target.lower() == 'subject':
        threads = STORE.search_subject(list_name, keyword)
    elif target.lower() == 'content':
        threads = STORE.search_content(list_name, keyword)
    elif target.lower() == 'from':
        threads = STORE.search_sender(list_name, keyword)
    
    return _search_results_page(request, mlist_fqdn, threads, 'Search', page)


def search_tag(request, mlist_fqdn, tag=None, page=1):
    '''Searches both tag and topic'''
    if tag:
        query_string = {'Category': tag.capitalize()}
    else:
        query_string = None
    return _search_results_page(request, mlist_fqdn, query_string,
        'Tag search', page, limit=50)

def thread (request, mlist_fqdn, threadid):
    ''' Displays all the email for a given thread identifier '''
    list_name = mlist_fqdn.split('@')[0]

    search_form = SearchForm(auto_id=False)
    t = loader.get_template('thread.html')
    threads = STORE.get_thread(list_name, threadid)
    #prev_thread = mongo.get_thread_name(list_name, int(threadid) - 1)
    prev_thread = []
    if len(prev_thread) > 30:
        prev_thread = '%s...' % prev_thread[:31]
    #next_thread = mongo.get_thread_name(list_name, int(threadid) + 1)
    next_thread = []
    if len(next_thread) > 30:
        next_thread = '%s...' % next_thread[:31]

    participants = {}
    cnt = 0
    for msg in threads:
        msg.email = msg.email.strip()
        # Statistics on how many participants and threads this month
        participants[msg.sender] = {'email': msg.email}
        cnt = cnt + 1

    archives_length = STORE.get_archives_length(list_name)
    from_url = '/thread/%s/%s/' %(mlist_fqdn, threadid)
    tag_form = AddTagForm(initial={'from_url' : from_url})
    print dir(search_form)

    c = RequestContext(request, {
        'app_name': settings.APP_NAME,
        'list_name' : list_name,
        'list_address': mlist_fqdn,
        'search_form': search_form,
        'addtag_form': tag_form,
        'month': 'Thread',
        'participants': participants,
        'answers': cnt,
        'first_mail': threads[0],
        'threads': threads[1:],
        'next_thread': next_thread,
        'next_thread_id': 0,
        'prev_thread': prev_thread,
        'prev_thread_id': 0,
        'archives_length': archives_length,
    })
    return HttpResponse(t.render(c))
