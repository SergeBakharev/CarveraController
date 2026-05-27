from pythonforandroid.recipe import CompiledComponentsPythonRecipe


class CythonRecipe(CompiledComponentsPythonRecipe):
    # Upstream p4a pins Cython 0.29.36, whose generated C calls
    # _PyLong_AsByteArray() with the pre-3.13 signature and fails to compile
    # against Python 3.14 (which p4a's develop branch now bundles):
    #   Cython/Plex/Scanners.c: error: too few arguments to function call,
    #   expected 6, have 5
    # Bump to a Cython that supports 3.14 (3.1.x; the same series the
    # PyProjectRecipes already pip-install to produce cp314 wheels).
    version = '3.1.8'
    url = 'https://github.com/cython/cython/archive/{version}.tar.gz'
    site_packages_name = 'cython'
    depends = ['setuptools']
    call_hostpython_via_targetpython = False
    install_in_hostpython = True


recipe = CythonRecipe()
