from pythonforandroid.recipe import Recipe
from pythonforandroid.logger import shprint
from pythonforandroid.toolchain import current_directory
import os
import glob

try:
    import sh
except ImportError:
    sh = None

class LibusbRecipe(Recipe):
    version = '1.0.27'
    url = 'https://github.com/libusb/libusb/releases/download/v{version}/libusb-{version}.tar.bz2'
    name = 'libusb'
    depends = []
    # We'll set built_libraries dynamically after build
    built_libraries = {}

    def get_recipe_env(self, arch):
        env = super().get_recipe_env(arch)
        # Set NDK path
        env['NDK'] = self.ctx.ndk_dir
        return env

    def build_arch(self, arch):
        # Loosely following https://github.com/libusb/libusb/blob/master/android/README

        if sh is None:
            raise RuntimeError('sh module is required to build this recipe')
        env = self.get_recipe_env(arch)
        # Unpack and cd to android/jni
        build_dir = self.get_build_dir(arch.arch)
        jni_dir = os.path.join(build_dir, 'android', 'jni')
        if not os.path.exists(jni_dir):
            raise RuntimeError(f'jni directory not found: {jni_dir}')
        with current_directory(jni_dir):
            shprint(sh.Command(env['NDK'] + '/ndk-build'), _env=env)
        # Find the .so file
        arch_map = {
            'armeabi-v7a': 'armeabi-v7a',
            'arm64-v8a': 'arm64-v8a',
            'x86_64': 'x86_64',
        }
        out_arch = arch_map.get(arch.arch, arch.arch)
        if not isinstance(out_arch, str):
            raise RuntimeError(f"Unsupported arch: {arch.arch}")
        so_dir = os.path.join(build_dir, 'android', 'libs', out_arch)
        so_files = glob.glob(os.path.join(so_dir, 'libusb1.0.so'))
        if not so_files:
            raise RuntimeError(f'libusb1.0.so not found in {so_dir}')
        # Set built_libraries for this arch
        self.built_libraries = {'libusb1.0.so': so_dir}

recipe = LibusbRecipe()