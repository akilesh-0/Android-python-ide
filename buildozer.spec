
[app]

title = Android Python IDE
package.name = androidpythonide
package.domain = org.akilesh

source.dir = .
source.include_exts = py,png,jpg,jpeg,kv,atlas,json,txt,ttf,otf,html,css,js,md
source.exclude_dirs = .git,.github,.buildozer,bin,venv,.venv,__pycache__

version = 0.1.0

# Core Kivy app dependencies.
# Pygame requires a compatible Android build recipe.
requirements = python3,kivy

orientation = portrait
fullscreen = 0

# Python-for-Android configuration
p4a.fork = kivy
p4a.branch = develop
p4a.bootstrap = sdl2

# Android SDK and NDK
android.api = 36
android.minapi = 24
android.ndk = 29
android.ndk_api = 24
android.archs = arm64-v8a

# Application permissions
android.permissions = INTERNET

# Build configuration
android.accept_sdk_license = True
android.allow_backup = True
android.debug_artifact = apk
android.release_artifact = apk

[buildozer]

log_level = 2
warn_on_root = 1
