from subprocess import CalledProcessError
from distutils.command.config import config
import re
import os
from popen2 import Popen3
from subprocess import Popen, PIPE
from tempfile import mkdtemp

from citools.git import fetch_repository

"""
Help us handle continuous versioning. Idea is simple: We have n-number digits
version (in form 1.2(.3...).n), where number of 1...(n-1) must appear in tag.

n is then computed as number-of-commits since last version-setting tag (and we're
using git describe for it now)
"""

def compute_version(string):
    """ Return VERSION tuple, computed from git describe output """
    match = re.match("(?P<bordel>[a-z0-9\-\_]*)(?P<arch>\d+\.\d+)(?P<rest>.*)", string)

    if not match or not match.groupdict().has_key('arch'):
        raise ValueError(u"String %s should be a scheme version, but it's not; failing" % str(string))

    version = match.groupdict()['arch']

    if match.groupdict().has_key('rest') and match.groupdict()['rest']:
        staging = re.findall("(\.\d+)", match.groupdict()['rest'])
        version = ''.join([version]+staging)


    # we're using integer version numbers instead of string
    build_match = re.match(".*(%(version)s){1}.*\-{1}(?P<build>\d+)\-{1}g{1}[0-9a-f]{7}" % {'version' : version}, string)

    if not build_match or not build_match.groupdict().has_key('build'):
        # if version is 0.0....
        if re.match("^0(\.0)+$", version):
            # return 0.0.1 instead of 0.0.0, as "ground zero version" is not what we want
            build = 1
        else:
            build = 0
    else:
        build = int(build_match.groupdict()['build'])

    return tuple(list(map(int, version.split(".")))+[build])

def sum_versions(version1, version2):
    """
    Return sum of both versions. Raise ValueError when negative number met
    i.e.:
    (0, 2) = (0, 1) + (0, 1)
    (1, 23, 12) = (0, 2, 12) + (1, 21)
    """
    final_version = [int(i) for i in version1 if int(i) >= 0]

    if len(final_version) != len(version1):
        raise ValueError("Negative number in version number not allowed")

    position = 0
    for part in version2:
        if int(part) < 0:
            raise ValueError("Negative number in version number not allowed")
        if len(final_version) < position+1:
            final_version.append(part)
        else:
            final_version[position] += part
        position += 1
    return tuple(final_version)


def get_git_describe(fix_environment=False, repository_directory=None, accepted_tag_pattern=None):
    """ Return output of git describe. If no tag found, initial version is considered to be 0.0.1 """
    if repository_directory and not fix_environment:
        raise ValueError("Both fix_environment and repository_directory or none of them must be given")
    
    if fix_environment:
        if not repository_directory:
            raise ValueError(u"Cannot fix environment when repository directory not given")
        env_git_dir = None
        if os.environ.has_key('GIT_DIR'):
            env_git_dir = os.environ['GIT_DIR']

        os.environ['GIT_DIR'] = os.path.join(repository_directory, '.git')


    command = ["git", "describe"]

    if accepted_tag_pattern is not None:
        command.append('--match="%s"' % accepted_tag_pattern)

    try:
        proc = Popen(' '.join(command), stdout=PIPE, stderr=PIPE, shell=True)
        stdout, stderr = proc.communicate()
        
        if proc.returncode == 0:
            return stdout.strip()

        elif proc.returncode == 128:
            return '0.0'

        else:
            raise ValueError("Unknown return code %s" % proc.returncode)

    finally:
        if fix_environment:
            if env_git_dir:
                os.environ['GIT_DIR'] = env_git_dir
            else:
                del os.environ['GIT_DIR']

def replace_version(source_file, version):
    content = []
    version_regexp = re.compile(r"^(VERSION){1}(\ )+(\=){1}(\ )+\({1}([0-9])+(\,{1}(\ )*[0-9]+)+(\)){1}")

    for line in source_file:
        if version_regexp.match(line):
            content.append('VERSION = %s\n' % str(version))
        else:
            content.append(line)
    return content

def get_git_head_hash(fix_environment=False, repository_directory=None):
    """ Return output of git describe. If no tag found, initial version is considered to be 0.0.1 """
    if fix_environment:
        if not repository_directory:
            raise ValueError(u"Cannot fix environment when repository directory not given")
        env_git_dir = None
        if os.environ.has_key('GIT_DIR'):
            env_git_dir = os.environ['GIT_DIR']

        os.environ['GIT_DIR'] = os.path.join(repository_directory, '.git')

    try:
        proc = Popen3("git rev-parse HEAD")
        return_code = proc.wait()
        if return_code == 0:
            return proc.fromchild.read().strip()
        else:
            raise ValueError("Non-zero return code %s from git log" % return_code)

    finally:
        if fix_environment:
            if env_git_dir:
                os.environ['GIT_DIR'] = env_git_dir
            else:
                del os.environ['GIT_DIR']


def replace_init(version, name):
    """ Update VERSION attribute in $name/__init__.py module """
    file = os.path.join(name, '__init__.py')
    replace_version_in_file(version, file)

def replace_inits(version, packages=None):
    if packages is None:
        packages = []
    for p in packages:
        p = p.replace('.', '/')
        replace_init(version, p)

def replace_scripts(version, scripts=None):
    if scripts is None:
        scripts = []
    for s in scripts:
        s = '%s.py' % s
        replace_version_in_file(version, s)

def replace_version_in_file(version, file):
    """ Update VERSION attribute in $name/__init__.py module """
    file = open(file, 'r')
    content = replace_version(version=version, source_file=file)
    file.close()
    file = open(file.name, 'wb')
    file.writelines(content)
    file.close()

def get_current_branch(branch_output):
    """
    Parse output of git branch --no-color and return proper result
    """
    for line in branch_output.splitlines():
        if line[2:] == "(no branch)":
            raise ValueError("We're outside of branch")
        elif line.startswith('*'):
            return line[2:]

    raise ValueError("No branch found")



def retrieve_current_branch(fix_environment=False, repository_directory=None, **kwargs):
    #######
    # FIXME: repository_directory and fix_environment artifact shall be refactored
    # in something like secure_and_fixed_git_command or something.
    # But pay attention to nested command in get_git_describe, it probably shall be using callback.
    # See #6679
    #######
    if repository_directory and not fix_environment:
        raise ValueError("Both fix_environment and repository_directory or none of them must be given")

    if fix_environment:
        if not repository_directory:
            raise ValueError(u"Cannot fix environment when repository directory not given")
        env_git_dir = None
        if os.environ.has_key('GIT_DIR'):
            env_git_dir = os.environ['GIT_DIR']

        os.environ['GIT_DIR'] = os.path.join(repository_directory, '.git')

    try:
        proc = Popen('git branch --no-color', stdout=PIPE, stderr=PIPE, shell=True)
        stdout, stderr = proc.communicate()

        if proc.returncode == 0:
            return get_current_branch(stdout)
        else:
            raise CalledProcessError("git branch returned exit code %s" % proc.returncode)

    finally:
        if fix_environment:
            if env_git_dir:
                os.environ['GIT_DIR'] = env_git_dir
            else:
                del os.environ['GIT_DIR']


def compute_meta_version(dependency_repositories, workdir=None, accepted_tag_pattern=None):

    kwargs = {}

    if workdir:
        kwargs.update({
            'repository_directory' : workdir,
            'fix_environment' : True
        })

    if accepted_tag_pattern:
        kwargs.update({
            'accepted_tag_pattern' : accepted_tag_pattern
        })

    describe = get_git_describe(**kwargs)
    meta_branch = retrieve_current_branch(**kwargs)

    version = compute_version(describe)
    
    repositories_dir = mkdtemp(dir=os.curdir, prefix="build-repository-dependencies-")
    for repository_dict in dependency_repositories:
        if repository_dict.has_key('branch'):
            branch = repository_dict['branch']
        else:
            branch = meta_branch
        workdir = fetch_repository(repository_dict['url'], branch=branch, workdir=repositories_dir)
        # this is pattern for dependency repo, NOT for for ourselves -> pattern of it, not ours
        # now hardcoded, but shall be retrieved via egg_info or custom command
        project_pattern = "%s-[0-9]*" % repository_dict['package_name']
        new_version = compute_version(get_git_describe(repository_directory=workdir, fix_environment=True, accepted_tag_pattern=project_pattern))
        version = sum_versions(version, new_version)
    return version

class GitSetMetaVersion(config):

    description = "calculate and set version from all dependencies"

    user_options = [
    ]

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        """
        Clone all dependencies into temporary directory. Collect all git_set_versions for all
        packages (including myself).
        Update on all places as in git_set_version.
        """
        try:
            format = "%s-[0-9]*" % self.distribution.metadata.get_name()
            meta_version = compute_meta_version(self.distribution.dependencies_git_repositories, accepted_tag_pattern=format)

            version = meta_version
            version_str = '.'.join(map(str, version))

            replace_inits(version, self.distribution.packages)
            replace_scripts(version, self.distribution.py_modules)

            replace_version_in_file(version, 'setup.py')

            self.distribution.metadata.version = version_str
            print "Current version is %s" % version_str
        except Exception:
            import traceback
            traceback.print_exc()
            raise

class GitSetVersion(config):

    description = "calculate version from git describe"

    user_options = [
    ]

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        """ Compute current version for tag and git describe. Expects VERSION variable to be stored in
        $name/__init__.py file (relatively placed to $cwd.) and to be a tuple of three integers.
        Because of line endings, should be not run on Windows."""
        try:
            # format is given, sorry. If you want it configurable, use paver
            format = "%s-[0-9]*" % self.distribution.metadata.get_name()

            current_git_version = get_git_describe(accepted_tag_pattern=format)

            version = compute_version(current_git_version)
            version_str = '.'.join(map(str, version))

            replace_inits(version, self.distribution.packages)
            replace_scripts(version, self.distribution.py_modules)

            replace_version_in_file(version, 'setup.py')

            if os.path.exists('pavement.py'):
                replace_version_in_file(version, 'pavement.py')

            self.distribution.metadata.version = version_str
            print "Current version is %s" % version_str
        except Exception:
            import traceback
            traceback.print_exc()
            raise

def validate_repositories(dist, attr, value):
    # TODO: 
    # http://peak.telecommunity.com/DevCenter/setuptools#adding-setup-arguments
    pass

