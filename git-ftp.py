#!/usr/bin/env python

"""
git-ftp: painless, quick and easy working copy syncing over FTP

Copyright (c) 2008-2009
Edward Z. Yang <ezyang@mit.edu> and Mauro Lizaur <mauro@cacavoladora.org>

Permission is hereby granted, free of charge, to any person
obtaining a copy of this software and associated documentation
files (the "Software"), to deal in the Software without
restriction, including without limitation the rights to use,
copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the
Software is furnished to do so, subject to the following
conditions:

The above copyright notice and this permission notice shall be
included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES
OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
OTHER DEALINGS IN THE SOFTWARE.
"""

import ftplib
import cStringIO
import sys
import os.path
import getpass
import ConfigParser
import optparse
import logging

from git import Tree, Blob, Repo, Git

def main():
    Git.git_binary = 'git' # Windows doesn't like env

    repo, options, args = parse_args()

    if repo.is_dirty:
        logging.warning("Working copy is dirty; uncommitted changes will NOT be uploaded")

    base = options.ftp.remotepath
    commit = repo.commits()[0]
    tree   = commit.tree
    ftp    = ftplib.FTP(options.ftp.hostname, options.ftp.username, options.ftp.password)

    # Check revision
    hash = None
    if not options.force:
        hashFile = cStringIO.StringIO()
        try:
            ftp.retrbinary('RETR ' + base + '/git-rev.txt', hashFile.write)
            hash = hashFile.getvalue()
        except ftplib.error_perm:
            pass

    if not hash:
        # Perform full upload
        upload_all(tree, ftp, base)
    else:
        upload_diff(repo.diff(hash, commit.id).split("\n"), tree, ftp, base)

    ftp.storbinary('STOR ' + base + '/git-rev.txt', cStringIO.StringIO(commit.id))
    ftp.quit()

def parse_args():
    usage = """usage: %prog [DIRECTORY]

This script uploads files in a Git repository to a
website via FTP, but is smart and only uploads file
that have changed."""
    parser = optparse.OptionParser(usage)
    parser.add_option('-f', '--force', dest="force", action="store_true", default=False,
            help="force the reupload of all files")
    parser.add_option('-v', '--verbose', dest="verbose", action="store_true", default=False,
            help="be verbose")
    options, args = parser.parse_args()
    configure_logging(options)
    if len(args) > 1:
        parser.error("too many arguments")
    if args: cwd = args[0]
    else: cwd = "."
    repo = Repo(cwd)
    get_ftp_creds(repo, options)
    return repo, options, args

def configure_logging(options):
    logger = logging.getLogger()
    if options.verbose: logger.setLevel(logging.INFO)
    ch = logging.StreamHandler(sys.stderr)
    formatter = logging.Formatter("%(levelname)s: %(message)s")
    ch.setFormatter(formatter)
    logger.addHandler(ch)

class FtpData():
    password = None
    username = None
    hostname = None
    remotepath = None

def get_ftp_creds(repo, options):
    """
    Retrieves the data to connect to the FTP from .git/ftpdata
    or interactively.

    ftpdata format example::

        [ftp]
        username=me
        password=s00perP4zzw0rd
        hostname=ftp.hostname.com
        remotepath=/htdocs
        repository=/home/me/website

    Please note that it isn't necessary to have this file,
    you'll be asked for the data every time you upload something.
    """

    ftpdata = os.path.join(repo.path, "ftpdata")
    options.ftp = FtpData()
    if os.path.isfile(ftpdata):
        logging.info("Using .git/ftpdata")
        cfg = ConfigParser.ConfigParser()
        cfg.read(ftpdata)

        # just in case you do not want to store your ftp password.
        try:
            options.ftp.password = cfg.get('ftp','password')
        except:
            options.ftp.password = getpass.getpass('FTP Password: ')
        options.ftp.username = cfg.get('ftp','username')
        options.ftp.hostname = cfg.get('ftp','hostname')
        options.ftp.remotepath = cfg.get('ftp','remotepath')
    else:
        options.ftp.username = raw_input('FTP Username: ')
        options.ftp.password = getpass.getpass('FTP Password: ')
        options.ftp.hostname = raw_input('FTP Hostname: ')
        options.ftp.remotepath = raw_input('Remote Path: ')

def upload_all(tree, ftp, base):
    """Upload all items in a Git tree.

    Keyword arguments:
    tree -- the git.Tree to upload contents of
    ftp  -- the active ftplib.FTP object to upload contents to
    base -- the string base directory to upload contents to in ftp. For example,
            base = '/www/www'. base must exist and must not have a trailing
            slash.

    """
    for item in tree.items():
        node = tree[item[0]]
        ftp.cwd(base)
        if isinstance(node, Tree):
            try:
                ftp.mkd(node.name)
            except ftplib.error_perm:
                pass
            upload_all(node, ftp, '/'.join((base, node.name)))
        else:
            file = cStringIO.StringIO(node.data)
            try:
                ftp.delete(node.name)
            except ftplib.error_perm:
                pass
            ftp.storbinary('STOR ' + node.name, file)
            ftp.voidcmd('SITE CHMOD 755 ' + node.name)
            logging.info('Uploaded ' + '/'.join((base, node.name)))

def upload_diff(diff, tree, ftp, base):
    """Upload and/or delete items according to a Git diff.

    Keyword arguments:
    diff -- a unified diff split into an array by newlines. Usually generated
            with: repo.diff(orig_id, new_id).split("\n")
    tree -- root git.Tree that diff file paths can be resolved to.
    ftp  -- the active ftplib.FTP object to upload contents to
    base -- the string base directory to upload contents to in ftp. For example,
            base = '/www/www'. base must exist and must not have a trailing
            slash.

    """
    for line in diff:
        if line.startswith('--- ') or line.startswith('+++ '):
            delete = line.startswith('---')
            file = line.split(' ', 1)[1]
            if file == '/dev/null':
                continue
            # Remove bogus a or b directory git prepends to names
            file = line.split('/', 1)[1]
            target = '/'.join((base, file))
            if delete:
                try:
                    ftp.delete(target)
                    logging.info('Deleted ' + target)
                except ftplib.error_perm:
                    pass
            else:
                node = tree/file
                if isinstance(node, Tree):
                    try:
                        ftp.mkd(target)
                        logging.info('Created directory ' + target)
                        # This holds the risk of missing files to upload if
                        # the directory is created, but the files are not
                        # complete.
                        upload_all(node, ftp, target)
                    except ftplib.error_perm:
                        pass
                elif isinstance(node, Blob):
                    file = cStringIO.StringIO(node.data)
                    ftp.storbinary('STOR ' + target, file)
                    ftp.voidcmd('SITE CHMOD 755 ' + target)
                    logging.info('Uploaded ' + target)
                # Don't do anything if there isn't any item; maybe it
                # was deleted.

if __name__ == "__main__":
    main()
