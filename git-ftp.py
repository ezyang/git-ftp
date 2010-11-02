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
import textwrap

from git import Tree, Blob, Repo, Git

def main():
    Git.git_binary = 'git' # Windows doesn't like env

    repo, options, args = parse_args()

    if repo.is_dirty:
        logging.warning("Working copy is dirty; uncommitted changes will NOT be uploaded")

    base = options.ftp.remotepath
    commit = repo.commit()
    tree   = commit.tree
    ftp    = ftplib.FTP(options.ftp.hostname, options.ftp.username, options.ftp.password)

    # Check revision
    hash = options.revision
    if not options.force and not hash:
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
        upload_diff(repo.git.diff("--name-status", hash, commit.hexsha).split("\n"), tree, ftp, base)

    ftp.storbinary('STOR ' + base + '/git-rev.txt', cStringIO.StringIO(commit.hexsha))
    ftp.quit()

def parse_args():
    usage = 'usage: %prog [OPTIONS] [DIRECTORY]'
    desc = """\
           This script uploads files in a Git repository to a
           website via FTP, but is smart and only uploads file
           that have changed.
           """
    parser = optparse.OptionParser(usage, description=textwrap.dedent(desc))
    parser.add_option('-f', '--force', dest="force", action="store_true", default=False,
            help="force the reupload of all files")
    parser.add_option('-v', '--verbose', dest="verbose", action="store_true", default=False,
            help="be verbose")
    parser.add_option('-r', '--revision', dest="revision", default=None,
            help="use this revision instead of the server stored one")
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

def format_mode(mode):
    return "%o" % (mode & 0o777)

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

    ftpdata = os.path.join(repo.git_dir, "ftpdata")
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
    for subtree in tree.trees:
        ftp.cwd(base)
        try:
            ftp.mkd(subtree.name)
        except ftplib.error_perm:
            pass
        upload_all(subtree, ftp, '/'.join((base, subtree.name)))

    ftp.cwd(base)
    for blob in tree.blobs:
        logging.info('Uploading ' + '/'.join((base, blob.name)))
        try:
            ftp.delete(blob.name)
        except ftplib.error_perm:
            pass
        ftp.storbinary('STOR ' + blob.name, blob.data_stream)
        ftp.voidcmd('SITE CHMOD ' + format_mode(blob.mode) + ' ' + blob.name)

def upload_diff(diff, tree, ftp, base):
    """Upload and/or delete items according to a Git diff.

    Keyword arguments:
    diff -- a diff of --name-status
    tree -- root git.Tree that diff file paths can be resolved to.
    ftp  -- the active ftplib.FTP object to upload contents to
    base -- the string base directory to upload contents to in ftp. For example,
            base = '/www/www'. base must exist and must not have a trailing
            slash.

    """
    dirs_present = []
    ftp.cwd(base)
    for line in diff:
        if not line: continue
        status, file = line.split("\t", 1)
        full_path = '/'.join((base, file))
        if status == "D":
            try:
                ftp.delete(file)
                logging.info('Deleted ' + full_path)
                # Now let's see if we need to remove some subdirectories
                subtree = tree
                dir_to_remove = []
                def dir_reduce(dirs, dir):
                    if dirs:
                        return dirs + [dirs[-1] + '/' + dir]
                    return [dir]
                for dir in reduce(dir_reduce, file.split("/")[:-1], []):
                    if subtree and dir[-1] in subtree:
                        subtree = subtree/dir[-1]
                    else:
                        subtree = None
                        dir_to_remove.append(dir)
                dir_to_remove.reverse()
                for dir in dir_to_remove:
                    ftp.rmd(dir)
            except ftplib.error_perm:
                pass
        else:
            components = file.split("/")
            subtree = tree
            for c in components[:-1]:
                subtree = subtree/c
                # We need to make sure the directory is present
                if subtree.path not in dirs_present:
                    try:
                        ftp.mkd(subtree.path)
                        dirs_present.append(subtree.path)
                    except ftplib.error_perm:
                        pass
            node = subtree/components[-1]
            assert isinstance(node, Blob)

            logging.info('Uploading ' + full_path)
            ftp.storbinary('STOR ' + file, node.data_stream)
            ftp.voidcmd('SITE CHMOD ' + format_mode(node.mode) + ' ' + file)
            # Don't do anything if there isn't any item; maybe it
            # was deleted.

if __name__ == "__main__":
    main()
