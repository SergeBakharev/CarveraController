#!/usr/bin/env python3
"""Compile the stock-carving C extension into native/lib (in-place)."""

from __future__ import annotations

import os
import subprocess
import sys
import sysconfig
from pathlib import Path


def _sources(native_dir: Path) -> list[Path]:
    names = ["profile.c", "heightmap.c", "cylindrical.c", "voxel.c", "laser.c", "_stock_carve.c"]
    return [native_dir / name for name in names]


def _output_path(native_dir: Path) -> Path:
    suffix = sysconfig.get_config_var("EXT_SUFFIX") or ".so"
    lib_dir = native_dir / "lib"
    lib_dir.mkdir(parents=True, exist_ok=True)
    return lib_dir / f"_stock_carve{suffix}"


def _cl_quote(path: Path | str) -> str:
    return '"' + str(path).replace('"', "") + '"'


def _windows_python_lib() -> Path:
    """Import library that resolves Py_* symbols when linking an extension."""
    ver = f"{sys.version_info.major}{sys.version_info.minor}"
    ext = sysconfig.get_config_var("EXT_SUFFIX") or ""
    debug = bool(sysconfig.get_config_var("Py_DEBUG")) or ext.endswith("_d.pyd")
    name = f"python{ver}{'_d' if debug else ''}.lib"
    candidates: list[Path] = []
    libdir = sysconfig.get_config_var("LIBDIR")
    if libdir:
        candidates.append(Path(libdir) / name)
    candidates.append(Path(sys.base_prefix) / "libs" / name)
    for path in candidates:
        if path.is_file():
            return path
    looked = ", ".join(str(path) for path in candidates)
    raise SystemExit(f"Python import library {name} not found. Looked in: {looked}")


def _windows_cmd(native_dir: Path, include: str, out: Path, sources: list[str]) -> list[str]:
    py_lib = _windows_python_lib()
    ext = sysconfig.get_config_var("EXT_SUFFIX") or ""
    debug = bool(sysconfig.get_config_var("Py_DEBUG")) or ext.endswith("_d.pyd")
    # /Fo must name a directory ending in a backslash. Double it so the
    # backslash does not escape the closing quote in cl's response file.
    fo = str(out.parent).replace("/", "\\").rstrip("\\") + "\\\\"
    lines = [
        "/nologo",
        "/O2",
        "/std:c11",
        "/MDd" if debug else "/MD",
        "/LD",
        "/I" + _cl_quote(include),
        "/I" + _cl_quote(native_dir),
        f'/Fo"{fo}"',
        *(_cl_quote(src) for src in sources),
        "/Fe:" + _cl_quote(out),
        "/link",
        "/LIBPATH:" + _cl_quote(py_lib.parent),
        py_lib.name,
    ]
    rsp = out.parent / "_stock_carve.rsp"
    rsp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    # Relative to cwd=native_dir so the @ argument itself has no spaces.
    return ["cl", "@lib/_stock_carve.rsp"]


def build() -> Path:
    native_dir = Path(__file__).resolve().parents[1] / "carveracontroller" / "addons" / "stock" / "simulator" / "native"
    include = sysconfig.get_config_var("INCLUDEPY")
    if not include:
        raise SystemExit("Python headers not found (INCLUDEPY). Install python3-dev.")
    out = _output_path(native_dir)
    sources = [str(path) for path in _sources(native_dir)]
    if sys.platform == "win32":
        cmd = _windows_cmd(native_dir, include, out, sources)
    else:
        cc = os.environ.get("CC", "cc")
        cflags = os.environ.get("CFLAGS", "")
        # Darwin extensions are Mach-O bundles. -shared yields a dylib whose
        # Py_* symbols fail to link, or that CPython refuses to load.
        if sys.platform == "darwin":
            link_flags = ["-bundle", "-undefined", "dynamic_lookup"]
        else:
            link_flags = ["-shared"]
        cmd = [
            cc,
            "-O3",
            "-std=c99",
            "-fPIC",
            *link_flags,
            "-Wall",
            "-Wextra",
            f"-I{include}",
            f"-I{native_dir}",
            *sources,
            "-o",
            str(out),
            "-lm",
        ]
        if cflags:
            cmd[1:1] = cflags.split()
    print(" ".join(cmd))
    subprocess.check_call(cmd, cwd=native_dir)
    if sys.platform == "win32":
        (native_dir / "lib" / "_stock_carve.rsp").unlink(missing_ok=True)
    print(f"built {out}")
    return out


if __name__ == "__main__":
    build()
