#!/usr/bin/env python
# -*- coding:utf-8 -*-
#
import unittest

git_ftp = __import__('git-ftp', globals(), locals(), ['parse_ftpignore', 'is_ignored', 'split_pattern'], -1)
parse_ftpignore = git_ftp.parse_ftpignore
is_ignored = git_ftp.is_ignored
split_pattern = git_ftp.split_pattern


class TestGitFtp(unittest.TestCase):

    def test_parse_ftpignore(self):
        patterns = '''
# comment and blank line

# negate patterns behaviour (not supported)
!fileX.txt
# directory match
config/
# shell glob (without /)
*swp
BasePresenter.php
# with /
css/*less
# beginning of path
/.htaccess
        '''
        self.assertEqual(parse_ftpignore(patterns.split("\n")),
            ['!fileX.txt', 'config/', '*swp', 'BasePresenter.php', 'css/*less', '/.htaccess']
        )
    pass

    def test_split_pattern(self):
        self.assertEqual(split_pattern('/foo/rand[/]om/dir/'), ['', 'foo\\Z(?ms)', 'rand[/]om\\Z(?ms)', 'dir\\Z(?ms)', '\\Z(?ms)'])
        self.assertEqual(split_pattern('/ano[/]her/bar/file[.-0]txt'), ['', 'ano[/]her\\Z(?ms)', 'bar\\Z(?ms)', 'file[.-0]txt\\Z(?ms)'])
        self.assertEqual(split_pattern('left[/right'), ['left\\[\\Z(?ms)', 'right\\Z(?ms)'])
        self.assertEqual(split_pattern('left[/notright]'), ['left[/notright]\\Z(?ms)'])
    pass

    def test_is_ignored(self):
        self.assertTrue(is_ignored('/foo/bar/', 'bar/'), 'Ending slash matches only dir.')
        self.assertFalse(is_ignored('/foo/bar', 'bar/'), 'Ending slash matches only dir.')
        self.assertTrue(is_ignored('/foo/bar/baz', 'bar/'), 'Ending slash matches only dir and path underneath it.')

        self.assertFalse(is_ignored('foo/bar', 'foo?*bar'), 'Slash must be matched explicitly.')

        self.assertTrue(is_ignored('/foo/bar/', 'bar'))
        self.assertTrue(is_ignored('/foo/bar', 'bar'))
        self.assertTrue(is_ignored('/foo/bar/baz', 'bar'))

        self.assertTrue(is_ignored('/foo/bar/file.txt', 'bar/*.txt'))
        self.assertFalse(is_ignored('/foo/bar/file.txt', '/*.txt'), 'Leading slash matches against root dir.')
        self.assertTrue(is_ignored('/file.txt', '/*.txt'), 'Leading slash matches against root dir.')

        self.assertTrue(is_ignored('/foo/bar/output.o', 'bar/*.[oa]'), 'Character group.')
        self.assertFalse(is_ignored('/aaa/bbb/ccc', 'aaa/[!b]*'), 'Character ignore.')
        self.assertTrue(is_ignored('/aaa/bbb/ccc', '[a-z][a-c][!b-d]'), 'Character range.')
    pass


if __name__ == '__main__':
    unittest.main()
