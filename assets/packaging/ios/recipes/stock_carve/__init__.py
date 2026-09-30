"""kivy-ios recipe: static libstock_carve.a plus an importable _stock_carve module."""

import os

from kivy_ios.toolchain import CythonRecipe

# kivy-ios chdirs into the recipe build dir before get_recipe_env, and recipe_dir
# is the relative path from the toolchain CLI. Freeze an absolute path at import.
_NATIVE_SRC = os.path.abspath(
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "..",
        "..",
        "..",
        "..",
        "carveracontroller",
        "addons",
        "stock",
        "simulator",
        "native",
    )
)


class StockCarveRecipe(CythonRecipe):
    version = "1.0.0"
    url = "src"
    library = "libstock_carve.a"
    depends = ["python3"]
    cythonize = False
    hostpython_prerequisites = []
    call_hostpython_via_targetpython = False

    def get_recipe_env(self, plat):
        env = super().get_recipe_env(plat)
        env["STOCK_CARVE_SRC"] = _NATIVE_SRC
        return env

    def install(self):
        self.install_python_package(name=self.so_filename("_stock_carve"), is_dir=False)


recipe = StockCarveRecipe()
