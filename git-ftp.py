#!/usr/bin/env python

import ftplib
import cStringIO
import sys

from git import Tree, Blob, Repo, Git

def uploadAll(tree, ftp, base):
    """Upload all items in a Git tree.
    
    Keyword arguments:
    tree -- the git.Tree to upload contents of
    ftp  -- the active ftplib.FTP object to upload contents to
    base -- the string base directory to upload contents to in ftp. For example,
            base = '/www/www'. base must exist and must not have a trailing
            slash.
    
    """
    for node in tree.contents:
        ftp.cwd(base)
        if isinstance(node, Tree):
            try:
                ftp.mkd(node.name)
            except ftplib.error_perm:
                pass
            uploadAll(node, ftp, '/'.join((base, node.name)))
        else:
            file = cStringIO.StringIO(node.data)
            try:
                ftp.delete(node.name)
            except ftplib.error_perm:
                pass
            ftp.storbinary('STOR ' + node.name, file)
            ftp.voidcmd('SITE CHMOD 755 ' + node.name)
            print 'Uploaded ' + '/'.join((base, node.name))

def uploadDiff(diff, tree, ftp, base):
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
        if line.startswith('---') or line.startswith('+++'):
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
                    print 'Deleted ' + target
                except ftplib.error_perm:
                    pass
            else:
                node = tree/file
                if isinstance(node, Tree):
                    try:
                        ftp.mkd(target)
                        print 'Created directory ' + target
                        # This holds the risk of missing files to upload if
                        # the directory is created, but the files are not
                        # complete.
                        uploadAll(node, ftp, target)
                    except ftplib.error_perm:
                        pass
                elif isinstance(node, Blob):
                    file = cStringIO.StringIO(node.data)
                    ftp.storbinary('STOR ' + target, file)
                    ftp.voidcmd('SITE CHMOD 755 ' + target)
                    print 'Uploaded ' + target
                # Don't do anything if there isn't any item; maybe it
                # was deleted.

# Begin main body

# Parse arguments
username = sys.argv[1] # bob
password = sys.argv[2] # foobar
ftpsite  = sys.argv[3] # example.com
base     = sys.argv[4] # /www/www (must already exist!)
reposite = sys.argv[5] # /home/bob/website

# Windows doesn't like env
Git.git_binary = 'git'

repo   = Repo(reposite)
commit = repo.commits('master', 1)[0];
tree   = commit.tree
ftp    = ftplib.FTP(ftpsite, username, password)

# Check revision
hashFile = cStringIO.StringIO()
try:
    ftp.retrbinary('RETR ' + base + '/git-rev.txt', hashFile.write)
    hash = hashFile.getvalue()
except ftplib.error_perm:
    hash = 0

if not hash:
    # Perform full upload
    uploadAll(tree, ftp, base)
else:
    uploadDiff(repo.diff(hash, commit.id).split("\n"), tree, ftp, base)

ftp.storbinary('STOR ' + base + '/git-rev.txt', cStringIO.StringIO(commit.id))
ftp.quit()
