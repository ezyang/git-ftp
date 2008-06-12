from git_python import *
import ftplib, cStringIO, sys

def uploadAll(tree, ftp, base):
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
            print 'Uploaded ' + '/'.join((base, node.name))

def uploadDiff(diff, tree, ftp, base):
    for line in diff:
        if line.startswith('---') or line.startswith('+++'):
            delete = line.startswith('---')
            file = line.split(' ', 2)[1]
            if file == '/dev/null':
                continue
            # Remove bogus a or b directory git prepends to names
            file = line.split('/', 2)[1]
            target = '/'.join((base, file))
            if delete:
                ftp.delete(target)
                print 'Deleted ' + target
            else:
                blob = tree/file
                file = cStringIO.StringIO(blob.data)
                ftp.storbinary('STOR ' + target, file)
                print 'Uploaded ' + target

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
