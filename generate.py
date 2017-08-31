import hashlib
import json
import os
import requests
import glob
import string
import csv

from jinja2 import Environment, FileSystemLoader

amo_server = os.getenv('AMO_SERVER', 'https://addons.mozilla.org')

override_error = [
    'mozilla_cc@internetdownloadmanager.com',
    'jid1-YcMV6ngYmQRA2w@jetpack',
    'onepassword4@agilebits.com',
    'light_plugin_F6F079488B53499DB99380A7E11A93F6@kaspersky.com',
    'jetpack-extension@dashlane.com'
]


def process_amo(addon, result, compat):
    try:
        name = result['name']['en-US']
    except KeyError:
        name = result['slug']
    return {
        'name': name,
        'url': result['url'],
        'guid': result['guid'],
        'status': compat['e10s'] == 'compatible-webextension',
        'id': result['id'],
        'users': addon.get('users', 0)
    }


def url_hash(url):
    hsh = hashlib.md5()
    hsh.update(url)
    return hsh.hexdigest()


def set_cache(url, result):
    filename = os.path.join('cache', url_hash(url) + '.json')
    json.dump(result, open(filename, 'w'))


def get_cache(url):
    filename = os.path.join('cache', url_hash(url) + '.json')
    if os.path.exists(filename):
        print 'Using cache:', filename
        return json.load(open(filename, 'r'))


def amo_error(addon, error):
    err = {
        'name': addon['name'],
        'url': '',
        'guid': addon['guid'],
        'status': addon['guid'] in override_error or error,
        'id': 0
    }
    return err


def get_from_amo(addon):
    guid = addon['guid']
    try:

        addon_url = amo_server + '/api/v3/addons/addon/{}/'.format(guid)
        addon_data = get_cache(addon_url)
    except UnicodeEncodeError:
        return amo_error(addon, 'Unicode error')

    compat_url = amo_server + '/api/v3/addons/addon/{}/feature_compatibility/'.format(guid)
    compat_data = get_cache(compat_url)
    if addon_data and compat_data:
        return process_amo(addon, addon_data, compat_data)

    data = []
    for url in (addon_url, compat_url):
        print 'Fetching', url
        res = requests.get(url)
        if res.status_code != 200:
            return amo_error(addon, 'AMO returned: %s' % res.status_code)

        res.raise_for_status()
        res_json = res.json()
        set_cache(url, res_json)
        data.append(res_json)

    return process_amo(addon, *data)


def tracker_bugs(uuid):
    return get_cached_bugzilla(
        'https://bugzilla.mozilla.org/rest/bug?whiteboard=[awe:%s]' % uuid
    )


def get_cached_bugzilla(url):
    cached = get_cache(url)
    if cached:
        return cached

    res = requests.get(url)
    try:
        res_json = res.json()
    except ValueError:
        print 'Failed to get JSON for: ' + url
        return {}
    set_cache(url, res_json)
    return res_json


def get_bug(id):
    return get_cached_bugzilla(
        'https://bugzilla.mozilla.org/rest/bug/%s' % id
    )

def get_blockers_from_bugzilla(addon):
    guid = addon['guid']
    trackers = tracker_bugs(guid)
    addon['trackers'] = []
    addon['trackers_open'] = []
    addon['trackers_bugs_open'] = []

    if not trackers:
        # Differentiate between no trackers existing and no trackers
        # being open at all.
        addon['trackers_open'] = None

    for tracker in trackers['bugs']:
        addon['trackers'].append(tracker['id'])
        if tracker['status'] in ('NEW', 'ASSIGNED', 'UNCONFIRMED'):
            addon['trackers_open'].append(tracker['id'])

        # Note this is not recursive.
        for bug_id in tracker['depends_on']:
            bug = get_bug(bug_id)['bugs'][0]
            if bug['status'] in ('NEW', 'ASSIGNED', 'UNCONFIRMED'):
                addon['trackers_bugs_open'].append(bug['id'])


def get_from_amo_and_bugzilla(addon):
    result = get_from_amo(addon)
    if result:
        get_blockers_from_bugzilla(result)
    return result


if __name__=='__main__':
    amo = json.load(open('addons-new.json', 'r'))
    for level, addons in amo.items():
        addons = [get_from_amo_and_bugzilla(addon) for addon in addons]
        amo[level] = addons

    env = Environment(loader=FileSystemLoader('.'))
    template = env.get_template('jinja-template.html')

    context = {
        'addons': amo
    }

    html = template.render(context)
    open('index.html', 'w').write(html.encode('utf-8'))
