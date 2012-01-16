#!/usr/bin/env python
# -*- coding: utf-8 -*-

import base64
import os
import re
from ConfigParser import ConfigParser
from getpass import getpass
from httplib import HTTPSConnection, HTTPException
from urlparse import urljoin, urlsplit
try:
    import json
except ImportError:
    try:
        import simplejson as json
    except ImportError:
        print "Couldn't find simplejson, please install it first."
        exit(2)

NAME = 'DelGists'
VERSION = '0.1'
AUTHOR = 'Mathieu D. (MatToufoutu)'

API_ROOT = 'https://api.github.com'
API_GISTS = urljoin(API_ROOT, 'gists')
USER_AGENT = 'Python-{0}/{1}'.format(NAME, VERSION)
DATETIME_FORMAT = '%Y-%m-%dT%H:%M:%SZ'
CONFIG_FILE = os.path.join(os.path.expanduser('~'), 'delgists.conf')


class CommandLine(object):
    """
    Command-line management (menus, formatting, etc...).
    """
    separator = '-'

    def get_term_size(self):
        """
        Portable (Win/Linux, untested for MacOS) way to get the terminal's size.
        """
        def ioctl_GWINSZ(fd):
            try:
                import fcntl, termios, struct
                cr = struct.unpack('hh', fcntl.ioctl(fd, termios.TIOCGWINSZ, '1234'))
            except Exception:
                return None
            return cr

        cr = ioctl_GWINSZ(0) or ioctl_GWINSZ(1) or ioctl_GWINSZ(2)
        if cr is None:
            try:
                fd = os.open(os.ctermid(), os.O_RDONLY)
                cr = ioctl_GWINSZ(fd)
                os.close(fd)
            except Exception:
                pass
        if cr is None:
            try:
                cr = (os.environ['LINES'], os.environ['COLUMNS'])
            except Exception:
                cr = (25, 80)
        return int(cr[0]), int(cr[1])

    def get_term_height(self):
        return self.get_term_size()[0]

    def get_term_width(self):
        return self.get_term_size()[1]

    def clear(self):
        for _ in xrange(self.get_term_height()):
            print ""

    def boxed_text(self, text):
        width = self.get_term_width()
        print self.separator * width
        print text.center(width)
        print self.separator * width

    def menu(self, options):
        opt_strings = ("[{0}] {1}".format(key, title) for key, title in options)
        menu_text = '| {0} |'.format(' | '.join(opt_strings))
        self.boxed_text(menu_text)
        w = self.get_term_width()
        choice = raw_input('Action: '.center(w)[:w/2+5])
        if choice.lower() not in [opt[0] for opt in options]:
            print "ERROR: Unknown choice: {0}".format(choice).center(w)
            return self.menu(options)
        print self.separator * w
        return choice


class GistBrowser(object):
    GISTS_PER_PAGE = 20
    NEXT = re.compile(r'^<(https://api\.github\.com/gists\?page=\d+)>; rel="next"')
    RANGE_RE = re.compile(r'^(\d+)-(\d+)$')

    def __init__(self):
        self.cli = CommandLine()
        self.conn = HTTPSConnection(host=urlsplit(API_ROOT).netloc)
        self.page = 1
        self.gists_per_page = 30
        self.user, self.passwd = self._get_api_credentials()
        self.headers = {
            'Connection': 'close',
            'User-Agent': USER_AGENT,
            'Authorization': 'Basic {0}'.format(base64.encodestring(
                '{0}:{1}'.format(self.user, self.passwd)
            ))
        }
        self.rate_limit = 0
        self.rate_remaining = 0
        self.page = 0
        self.pages = []

    def _get_api_credentials(self):
        c = ConfigParser()
        if not os.path.exists(CONFIG_FILE):
            # prompt user for credentials and create the config file
            print "You didn't set your GitHub credentials yet!"
            user = raw_input("Username: ")
            passwd = getpass()
            c.add_section('github')
            c.set('github', 'user', user)
            c.set('github', 'passwd', passwd)
            f = open(CONFIG_FILE, 'wb')
            try:
                c.write(f)
            finally:
                f.close()
            return user, passwd
        c.read(CONFIG_FILE)
        user = c.get('github', 'user')
        passwd = c.get('github', 'passwd')
        return user, passwd

    def _request(self, method, uri, body=None, status_ok='200 OK', has_data=True):
        self.conn.request(method, uri, body=body, headers=self.headers)
        response = self.conn.getresponse()
        resp_headers = dict(response.getheaders())
#        print resp_headers #XXX: debug
        if resp_headers.get('status', None) != status_ok:
            print response.read() #XXX: debug
            raise HTTPException(resp_headers['status'])
        self.rate_limit = resp_headers['x-ratelimit-limit']
        self.rate_remaining = resp_headers['x-ratelimit-remaining']
        #XXX: debug
#        tmp = response.read()
#        print tmp
#        data = json.loads(tmp)
        data = json.load(response) if has_data else response
        return response, data

    def get(self, gist_id):
        endpoint = 'gists/{1}'.format(gist_id)
        uri = urljoin(API_ROOT, endpoint)
        return self._request('GET', uri)[1]

    def get_all(self):
        gists = []
        resp, data = self._request('GET', API_GISTS)
        gists.extend(data)
        link = resp.getheader('link')
        if link is not None:
            next_page = self.NEXT.search(link)
            while next_page is not None:
                next_page = next_page.group(1)
                resp, data = self._request('GET', next_page)
                gists.extend(data)
                next_page = self.NEXT.search(resp.getheader('link'))
        return gists

    def delete(self, gist_id):
        endpoint = 'gists/{0}'.format(gist_id)
        uri = urljoin(API_ROOT, endpoint)
        return self._request('DELETE', uri,
                             status_ok='204 No Content',
                             has_data=False)[1]

    def _display_current_page(self):
        self.cli.clear()
        print '-' * self.cli.get_term_width()
        for index, gist in enumerate(self.pages[self.page]):
            desc = gist['description'] or gist['html_url']
            padding = 0
            if index <= 8:
                padding = 1
            print "[{0}{1}] {2}".format(padding*' ', index+1, desc)

    def run(self):
        self.cli.boxed_text("Welcome to DelGists")
        gists = self.get_all()
        self.pages = [gists[i:i+self.GISTS_PER_PAGE] for i in xrange(
            0, len(gists), self.GISTS_PER_PAGE
        )]
        self._display_current_page()
        while True:

            # generate menu choices
            choices = [
#                ('s', 'Show Gist'),
                ('d', 'Delete Gist'),
                ('q', 'Quit')
            ]
            if self.page > 0:
                choices.insert(0, ('p', 'Previous Page'))
            if self.page < len(self.pages)-1:
                choices.append(('n', 'Next Page'))
            choice = self.cli.menu(choices).lower()

            # handle previous/next page
            if choice in ('p', 'n'):
                if choice == 'p':
                    self.page -= 1
                elif choice == 'n':
                    self.page += 1

            #TODO: handle gist deletion
            elif choice == 'd':
                w = self.cli.get_term_width()
                selected = raw_input("Gist IDs/range: ".center(w)[:w/2+9])
                selected = selected.replace(' ', '')
                match = self.RANGE_RE.search(selected)
                if match is not None:
                    begin, end = match.groups()
                    print begin, end #XXX: debug
                    if begin >= end:
                        print "First index is greater than last"
                        # NOTE: display a warning here?
                        continue
                    for index in xrange(int(begin), int(end)+1):
                        real_index = index-1
                        gist = self.pages[self.page][real_index]
                        print real_index, gist['description'] or gist['html_url'] #XXX: debug
#                        self.delete(gist['id']) #XXX: debug
#                        self.pages[self.page].remove(gist)
                        del self.pages[self.page][real_index]
                else:
                    selected = set(selected.split(','))
                    if not all(i.isdigit() for i in selected):
                        # NOTE: display a warning here?
                        print "Invalid list of IDs"
                        continue
                    for index in selected:
                        if index in range(1, 21):
                            real_index = index-1
                            print real_index
                            gist = self.pages[self.page][real_index]
#                            self.delete(gist['id'])
                            del self.pages[self.page][real_index]


            # TODO: implement single gist display
#            elif choice == 's':
#                pass

            elif choice == 'q':
                break

            self._display_current_page()



def main():
    browser = GistBrowser()
    try:
        browser.run()
    except KeyboardInterrupt:
        pass
    browser.cli.boxed_text("GoodBye!")

if __name__ == '__main__':
    main()
