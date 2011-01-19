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

class BranchNotFound(Exception):
    pass

class FtpDataOldVersion(Exception):
    pass

def main():
    Git.git_binary = 'git' # Windows doesn't like env

    repo, options, args = parse_args()

    if repo.is_dirty() and not options.commit:
        logging.warning("Working copy is dirty; uncommitted changes will NOT be uploaded")

    base = options.ftp.remotepath
    try:
        branch = (h for h in repo.heads if h.name == options.branch).next()
    except StopIteration:
        raise BranchNotFound
    commit = branch.commit
    if options.commit:
        commit = repo.commit(options.commit)
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
    parser.add_option('-q', '--quiet', dest="quiet", action="store_true", default=False,
            help="quiet output")
    parser.add_option('-r', '--revision', dest="revision", default=None,
            help="use this revision instead of the server stored one")
    parser.add_option('-b', '--branch', dest="branch", default=None,
            help="use this branch instead of the active one")
    parser.add_option('-c', '--commit', dest="commit", default=None,
            help="use this commit instead of HEAD")
    options, args = parser.parse_args()
    configure_logging(options)
    if len(args) > 1:
        parser.error("too many arguments")
    if args: cwd = args[0]
    else: cwd = "."
    repo = Repo(cwd)

    if not options.branch:
        options.branch = repo.active_branch.name

    get_ftp_creds(repo, options)
    return repo, options, args

def configure_logging(options):
    logger = logging.getLogger()
    if not options.quiet: logger.setLevel(logging.INFO)
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

    ftpdata format example:

        [branch]
        username=me
        password=s00perP4zzw0rd
        hostname=ftp.hostname.com
        remotepath=/htdocs

    Please note that it isn't necessary to have this file,
    you'll be asked for the data every time you upload something.
    """

    ftpdata = os.path.join(repo.git_dir, "ftpdata")
    options.ftp = FtpData()
    if os.path.isfile(ftpdata):
        logging.info("Using .git/ftpdata")
        cfg = ConfigParser.ConfigParser()
        cfg.read(ftpdata)

        if (not cfg.has_section(options.branch)) and cfg.has_section('ftp'):
            raise FtpDataOldVersion("Please rename the [ftp] section to [branch]. " +
                                    "Take a look at the README for more information")

        # just in case you do not want to store your ftp password.
        try:
            options.ftp.password = cfg.get(options.branch,'password')
        except ConfigParser.NoOptionError:
            options.ftp.password = getpass.getpass('FTP Password: ')

        options.ftp.username = cfg.get(options.branch,'username')
        options.ftp.hostname = cfg.get(options.branch,'hostname')
        options.ftp.remotepath = cfg.get(options.branch,'remotepath')
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
        upload_blob(blob, ftp, base)

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

            upload_blob(node, ftp, base)

def is_special_file(name):
    """Returns true if a file is some special Git metadata and not content."""
    return name.split('/')[-1] == '.gitignore'

def upload_blob(blob, ftp, base):
    """Uploads a blob."""
    fullname = '/'.join([base, blob.name])
    if is_special_file(blob.name):
        logging.info('Skipped ' + fullname)
        return
    logging.info('Uploading ' + fullname)
    try:
        ftp.delete(blob.name)
    except ftplib.error_perm:
        pass
    ftp.storbinary('STOR ' + blob.name, blob.data_stream)
    ftp.voidcmd('SITE CHMOD ' + format_mode(blob.mode) + ' ' + blob.name)

if __name__ == "__main__":
    main()
