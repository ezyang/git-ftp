#!/usr/bin/env python

"""
git-ftp: painless, quick and easy working copy syncing over FTP

Copyright (c) 2008-2011
Edward Z. Yang <ezyang@mit.edu>, Mauro Lizaur <mauro@cacavoladora.org> and
Niklas Fiekas <niklas.fiekas@googlemail.com>

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
import posixpath # use this for ftp manipulation
import getpass
import ConfigParser
import optparse
import logging
import textwrap

# Note about Tree.path/Blob.path: *real* Git trees and blobs don't
# actually provide path information, but the git-python bindings, as a
# convenience keep track of this if you access the blob from an index.
# This ends up considerably simplifying our code, but do be careful!

from distutils.version import LooseVersion
from git import __version__ as git_version

if LooseVersion(git_version) < '0.3.0':
    print 'git-ftp requires git-python 0.3.0 or newer; %s provided.' % git_version
    exit(1)

from git import Tree, Blob, Repo, Git, Submodule

class BranchNotFound(Exception):
    pass

class FtpDataOldVersion(Exception):
    pass

class FtpSslNotSupported(Exception):
    pass

def main():
    Git.git_binary = 'git' # Windows doesn't like env

    repo, options, args = parse_args()

    if repo.is_dirty() and not options.commit:
        logging.warning("Working copy is dirty; uncommitted changes will NOT be uploaded")

    base = options.ftp.remotepath
    logging.info("Base directory is %s", base)
    try:
        branch = (h for h in repo.heads if h.name == options.branch).next()
    except StopIteration:
        raise BranchNotFound
    commit = branch.commit
    if options.commit:
        commit = repo.commit(options.commit)
    tree   = commit.tree
    if options.ftp.ssl:
        if hasattr(ftplib, 'FTP_TLS'): # SSL new in 2.7+
            ftp = ftplib.FTP_TLS(options.ftp.hostname, options.ftp.username, options.ftp.password)
            ftp.prot_p()
            logging.info("Using SSL")
        else:
            raise FtpSslNotSupported("Python is too old for FTP SSL. Try using Python 2.7 or later.")
    else:
        ftp = ftplib.FTP(options.ftp.hostname, options.ftp.username, options.ftp.password)
    ftp.cwd(base)

    # Check revision
    hash = options.revision
    if not options.force and not hash:
        hashFile = cStringIO.StringIO()
        try:
            ftp.retrbinary('RETR git-rev.txt', hashFile.write)
            hash = hashFile.getvalue()
        except ftplib.error_perm:
            pass

    if not hash:
        # Diffing against an empty tree will cause a full upload.
        oldtree = get_empty_tree(repo)
    else:
        oldtree = repo.commit(hash).tree

    if oldtree.hexsha == tree.hexsha:
        logging.info('Nothing to do!')
    else:
        upload_diff(repo, oldtree, tree, ftp, base)

    ftp.storbinary('STOR git-rev.txt', cStringIO.StringIO(commit.hexsha))
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
    ssl = None

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
        ssl=yes

    Please note that it isn't necessary to have this file,
    you'll be asked for the data every time you upload something.
    """

    ftpdata = os.path.join(repo.git_dir, "ftpdata")
    options.ftp = FtpData()
    cfg = ConfigParser.ConfigParser()
    if os.path.isfile(ftpdata):
        logging.info("Using .git/ftpdata")
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
        try:
            options.ftp.ssl = boolish(cfg.get(options.branch,'ssl'))
        except ConfigParser.NoOptionError:
            options.ftp.ssl = False
    else:
        print "Please configure settings for branch '%s'" % options.branch
        options.ftp.username = raw_input('FTP Username: ')
        options.ftp.password = getpass.getpass('FTP Password: ')
        options.ftp.hostname = raw_input('FTP Hostname: ')
        options.ftp.remotepath = raw_input('Remote Path: ')
        if hasattr(ftplib, 'FTP_TLS'):
            options.ftp.ssl = ask_ok('Use SSL? ')
        else:
            logging.warning("SSL not supported, defaulting to no")

        # set default branch
        if ask_ok("Should I write ftp details to .git/ftpdata? "):
            cfg.add_section(options.branch)
            cfg.set(options.branch, 'username', options.ftp.username)
            cfg.set(options.branch, 'password', options.ftp.password)
            cfg.set(options.branch, 'hostname', options.ftp.hostname)
            cfg.set(options.branch, 'remotepath', options.ftp.remotepath)
            cfg.set(options.branch, 'ssl', options.ftp.ssl)
            f = open(ftpdata, 'w')
            cfg.write(f)

def get_empty_tree(repo):
    return repo.tree(repo.git.hash_object('-w', '-t', 'tree', os.devnull))

def upload_diff(repo, oldtree, tree, ftp, base):
    """
    Upload  and/or delete items according to a Git diff between two trees.

    upload_diff requires, that the ftp working directory is set to the base
    of the current repository before it is called.

    Keyword arguments:
    repo    -- The git.Repo to upload objects from
    oldtree -- The old tree to diff against. An empty tree will cause a full
               upload of the new tree.
    tree    -- The new tree. An empty tree will cause a full removal of all
               objects of the old tree.
    ftp     -- The active ftplib.FTP object to upload contents to
    base    -- the string base directory to upload contents to in ftp.
               For example, base = '/www/www'. base must exist and must not
               have a trailing slash.

    """
    diff = repo.git.diff("--name-status", "--no-renames", oldtree.hexsha, tree.hexsha).split("\n")
    for line in diff:
        if not line: continue
        status, file = line.split("\t", 1)
        assert status in ['A', 'D', 'M']

        if status == "D":
            try:
                ftp.delete(file)
                logging.info('Deleted ' + file)
            except ftplib.error_perm:
                logging.warning('Failed to delete ' + file)
            # Now let's see if we need to remove some subdirectories
            def generate_parent_dirs(x):
                # invariant: x is a filename
                while '/' in x:
                    x = posixpath.dirname(x)
                    yield x
            for dir in generate_parent_dirs(file):
                try:
                    # unfortunately, dir in tree doesn't work for subdirs
                    tree[dir]
                except KeyError:
                    try:
                        ftp.rmd(dir)
                        logging.debug('Cleaned away ' + dir)
                    except ftplib.error_perm:
                        logging.info('Did not clean away ' + dir)
                        break
        else:
            node = tree[file]

            if status == "A":
                # try building up the parent directory
                subtree = tree
                if isinstance(node, Blob):
                    directories = file.split("/")[:-1]
                else:
                    # for submodules also add the directory itself
                    assert isinstance(node, Submodule)
                    directories = file.split("/")
                for c in directories:
                    subtree = subtree/c
                    try:
                        ftp.mkd(subtree.path)
                    except ftplib.error_perm:
                        pass

            if isinstance(node, Blob):
                upload_blob(node, ftp)
            else:
                module = node.module()
                module_tree = module.commit(node.hexsha).tree
                if status == "A":
                    module_oldtree = get_empty_tree(module)
                else:
                    oldnode = oldtree[file]
                    assert isinstance(oldnode, Submodule) # TODO: What if not?
                    module_oldtree = module.commit(oldnode.hexsha).tree
                module_base = posixpath.join(base, node.path)
                logging.info('Entering submodule %s', node.path)
                ftp.cwd(module_base)
                upload_diff(module, module_oldtree, module_tree, ftp, module_base)
                logging.info('Leaving submodule %s', node.path)
                ftp.cwd(base)

def is_special_file(name):
    """Returns true if a file is some special Git metadata and not content."""
    return posixpath.basename(name) in ['.gitignore', '.gitattributes', '.gitmodules']

def upload_blob(blob, ftp, quiet = False):
    """
    Uploads a blob.  Pre-condition on ftp is that our current working
    directory is the root directory of the repository being uploaded
    (that means DON'T use ftp.cwd; we'll use full paths appropriately).
    """
    if is_special_file(blob.name):
        if not quiet: logging.info('Skipped ' + blob.path)
        return
    if not quiet: logging.info('Uploading ' + blob.path)
    try:
        ftp.delete(blob.path)
    except ftplib.error_perm:
        pass
    ftp.storbinary('STOR ' + blob.path, blob.data_stream)
    try:
        ftp.voidcmd('SITE CHMOD ' + format_mode(blob.mode) + ' ' + blob.path)
    except ftplib.error_perm:
        # Ignore Windows chmod errors
        logging.warning('Failed to chmod ' + blob.path)
        pass

def boolish(s):
    if s in ('1', 'true', 'y', 'ye', 'yes', 'on'): return True
    if s in ('0', 'false', 'n', 'no', 'off'): return False
    return None

def ask_ok(prompt, retries=4, complaint='Yes or no, please!'):
    while True:
        ok = raw_input(prompt).lower()
        r = boolish(ok)
        if r is not None:
            return r
        retries = retries - 1
        if retries < 0:
            raise IOError('Wrong user input.')
        print complaint

if __name__ == "__main__":
    main()
