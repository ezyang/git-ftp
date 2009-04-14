#!/usr/bin/env python

import ftplib
import cStringIO

from sys import argv
from getpass import getpass
from os.path import isfile
import ConfigParser

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
    for item in tree.items():
        node = tree[item[0]]
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

def getFtpData():
  """Retrieves the data to connect to the FTP from .git/ftpdata

  ftpdata format example:
   [ftp]
   username=me
   password=s00perP4zzw0rd
   hostname=ftp.hostname.com
   remotepath=/htdocs
   repository=/home/me/website 
  
  Please note that it isn't necesary to have this file,
  you'll be asked for the data every time you upload something.
  """
  FtpUser = FtpPassword = FtpHostname = ''
  Repository = RemotePath = ''

  if isfile(".git/ftpdata"):
    cfg = ConfigParser.ConfigParser()
    cfg.read(".git/ftpdata")

    # just in case you do not want to store your ftp password.
    try:
      FtpPassword = cfg.get('ftp','password')
    except: 
      FtpPassword = getpass('FTP Password: ')
    
    FtpUser = cfg.get('ftp','username')
    FtpHostname = cfg.get('ftp','hostname')
    Repository = cfg.get('ftp','repository')
    RemotePath = cfg.get('ftp','remotepath')
  else:
    FtpUser = raw_input('FTP Username: ')
    FtpPassword = getpass('FTP Password: ')
    FtpHostname = raw_input('FTP Hostname: ')
    Repository = raw_input('Repository Path: ')
    RemotePath = raw_input('Remote Path: ')

  return {'username': FtpUser, 
          'password': FtpPassword,
          'hostname': FtpHostname,
          'repository': Repository,
          'remotepath': RemotePath,
          }

# Begin main body

# Parse arguments
FtpData = getFtpData()
username = FtpData['username']
password = FtpData['password']  
ftpsite  = FtpData['hostname']
base     = FtpData['remotepath']
reposite = FtpData['repository']

# Windows doesn't like env
Git.git_binary = 'git'

repo   = Repo(reposite)
commit = repo.commits()[0]
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
