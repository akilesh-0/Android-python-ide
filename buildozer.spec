
[app]

title = Android Python IDE
package.name = androidpythonide
package.domain = org.akilesh

source.dir = .
source.include_exts = py

version = 0.1.0

requirements = python3,kivy

orientation = portrait
fullscreen = 0

android.api = 35
android.minapi = 24
android.archs = arm64-v8a
android.accept_sdk_license = True

[buildozer]

log_level = 2
warn_on_root = 1
